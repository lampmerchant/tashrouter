'''RTMP responding Service.'''

from collections import deque
from queue import Queue
import struct
from threading import Thread, Event

from . import RtmpService
from .. import Service
from ...datagram import Datagram
from ...router.routing_table import RoutingTableEntry


class RtmpRespondingService(Service, RtmpService):
  '''A Service which responds to inbound RTMP Datagrams and maintains the Router's RoutingTable.'''
  
  def __init__(self):
    self.thread = None
    self.started_event = Event()
    self.queue = Queue()
    self.stop_flag = object()
  
  def start(self, router):
    self.thread = Thread(target=self._run, args=(router,))
    self.thread.start()
    self.started_event.wait()
  
  def stop(self):
    self.queue.put(self.stop_flag)
    self.queue.join()
  
  def _run(self, router):
    
    while True:
      
      if self.started_event.is_set():
        self.queue.task_done()
      else:
        self.started_event.set()
      
      item = self.queue.get()
      if item is self.stop_flag: break
      datagram, rx_port = item
      
      if datagram.ddp_type == self.RTMP_DDP_TYPE_DATA:
        
        # process header
        if len(datagram.data) < 4: continue  # invalid, datagram too short
        sender_network, id_length, sender_node = struct.unpack('>HBB', datagram.data[0:4])
        if id_length != 8: continue  # invalid, AppleTalk node numbers are only 8 bits in length
        data = datagram.data[4:]
        if rx_port.extended_network:
          if len(data) < 6: continue  # invalid, datagram too short to contain at least one extended network tuple
          sender_network_min, range_distance, sender_network_max, rtmp_version = struct.unpack('>HBHB', data[0:6])
          if range_distance != 0x80: continue  # invalid, first tuple must be the sender's extended network tuple
        else:
          if len(data) < 3: continue
          sender_network_min = sender_network_max = sender_network
          zero, rtmp_version = struct.unpack('>HB', data[0:3])
          if zero != 0: continue  # invalid, this word must be zero on a nonextended network
          data = data[3:]
        if rtmp_version != self.RTMP_VERSION: continue  # invalid, don't recognize this RTMP format
        
        # interpret tuples
        tuples = deque()
        data_idx = 0
        while True:
          packed = data[data_idx:data_idx + 3]
          if len(packed) != 3: break
          network_min, range_distance = struct.unpack('>HB', packed)
          if range_distance & 0x80:
            packed = data[data_idx + 3:data_idx + 6]
            if len(packed) != 3: break
            network_max, _ = struct.unpack('>HB', packed)
            data_idx += 6
          else:
            network_max = None
            data_idx += 3
          tuples.append((network_min, network_max, range_distance & 0x1F))
        if data_idx != len(data): continue  # invalid, tuples did not end where expected
        
        # if this Port doesn't know its network range yet, accept that this is from the network's seed router
        if rx_port.network_min == rx_port.network_max == 0: rx_port.set_network_range(sender_network_min, sender_network_max)
        
        # resolve the given tuples with the current RoutingTable
        for network_min, network_max, distance in tuples:
          # if the entry is too many hops away or is a notify-neighbor entry, mark any entry we have as bad
          if distance >= 15:
            router.routing_table.mark_bad(network_min, network_max)
          # otherwise have the table consider a new entry based on this tuple
          else:
            router.routing_table.consider(RoutingTableEntry(network_min=network_min,
                                                            network_max=network_max,
                                                            distance=distance + 1,
                                                            port=rx_port,
                                                            next_network=sender_network,
                                                            next_node=sender_node))
        
      elif datagram.ddp_type != self.RTMP_DDP_TYPE_REQUEST or not datagram.data:
        
        continue
        
      elif datagram.data[0] == self.RTMP_FUNC_REQUEST:
        
        if 0 in (rx_port.network_min, rx_port.network_max): continue
        if datagram.hop_count != 0: continue  # we have to send responses out of the same port they came in, no routing
        response_data = struct.pack('>HBB', rx_port.network, 8, rx_port.node)
        if rx_port.extended_network:
          response_data += struct.pack('>HBHB', rx_port.network_min, 0x80, rx_port.network_max, self.RTMP_VERSION)
        rx_port.send(datagram.source_network, datagram.source_node, Datagram(hop_count=0,
                                                                             destination_network=datagram.source_network,
                                                                             source_network=rx_port.network,
                                                                             destination_node=datagram.source_node,
                                                                             source_node=rx_port.node,
                                                                             destination_socket=datagram.source_socket,
                                                                             source_socket=datagram.destination_socket,
                                                                             ddp_type=1,
                                                                             data=response_data))
        
      elif datagram.data[0] in (self.RTMP_FUNC_RDR_SPLIT_HORIZON, self.RTMP_FUNC_RDR_NO_SPLIT_HORIZON):
        
        split_horizon = True if datagram.data[0] == self.RTMP_FUNC_RDR_SPLIT_HORIZON else False
        for datagram_data in self.make_routing_table_datagram_data(router, rx_port, split_horizon):
          router.route(Datagram(hop_count=0,
                                destination_network=datagram.source_network,
                                source_network=rx_port.network,
                                destination_node=datagram.source_node,
                                source_node=rx_port.node,
                                destination_socket=datagram.source_socket,
                                source_socket=datagram.destination_socket,
                                ddp_type=self.RTMP_DDP_TYPE_DATA,
                                data=datagram_data))
    
    self.queue.task_done()
  
  def inbound(self, datagram, rx_port):
    self.queue.put((datagram, rx_port))
