'''RTMP responding Service.'''

from collections import deque
from queue import Queue
import struct
from threading import Thread, Event

from . import RtmpService
from .. import Service
from ...port import Port
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
        if len(datagram.data) < 3: continue  # invalid, datagram too short
        sender_network, id_length = struct.unpack('>HB', datagram.data[0:3])
        if id_length == 8:
          if len(datagram.data) < 4: continue  # invalid, datagram too short
          sender_node = datagram.data[3]
          data = datagram.data[4:]
        elif id_length == 0:
          sender_node = 0
          data = datagram.data[3:]
        else:
          continue  #TODO in what case would ID length be something other than 0 or 8?
        
        # determine from data (not from port type) whether it comes from an extended or nonextended network
        if len(data) < 3: continue  # invalid, datagram too short
        zero, rtmp_version = struct.unpack('>HB', data[0:3])
        if zero == 0:
          if rtmp_version != self.RTMP_VERSION: continue  # invalid, don't recognize this RTMP format
          first_tuple_net_range = False
          data = data[3:]
        else:
          first_tuple_net_range = True
        
        # interpret tuples
        tuple_violation = False
        sender_network_min = sender_network_max = None
        tuples = deque()
        data_idx = 0
        while True:
          packed = data[data_idx:data_idx + 3]
          if len(packed) != 3: break
          network_min, range_distance = struct.unpack('>HB', packed)
          if range_distance & 0x80:
            extended_network = True
            packed = data[data_idx + 3:data_idx + 6]
            if len(packed) != 3: break
            network_max, rtmp_version = struct.unpack('>HB', packed)
            if rtmp_version != self.RTMP_VERSION: tuple_violation = True  # invalid, don't recognize this RTMP format
            data_idx += 6
            if first_tuple_net_range:
              first_tuple_net_range = False
              sender_network_min = network_min
              sender_network_max = network_max
              if range_distance & 0x1F: tuple_violation = True  # invalid, first tuple must be the sender's extended network tuple
              continue  # this is the sender's extended network tuple, do not consider it as a routing table entry
          else:
            extended_network = False
            network_max = network_min
            data_idx += 3
            if first_tuple_net_range:
              first_tuple_net_range = False
              tuple_violation = True  # invalid, first tuple must be the sender's extended network tuple
          tuples.append((extended_network, network_min, network_max, range_distance & 0x1F))
        if data_idx != len(data): continue  # invalid, tuples did not end where expected
        if tuple_violation: continue  # invalid, see above for reason
        
        # if this Port doesn't know its network range yet, accept that this is from the network's seed router
        if rx_port.port_type == Port.PORT_TYPE_EXTENDED_NETWORK:
          #TODO is this how an extended network port should determine its network range?
          if rx_port.network_min == rx_port.network_max == 0 and None not in (sender_network_min, sender_network_max):
            rx_port.set_network_range(sender_network_min, sender_network_max)
        elif rx_port.port_type == Port.PORT_TYPE_NON_EXTENDED_NETWORK:
          if rx_port.network_min == rx_port.network_max == 0 and sender_network:
            rx_port.set_network_range(sender_network, sender_network)
        
        # resolve the given tuples with the current RoutingTable
        for extended_network, network_min, network_max, distance in tuples:
          # if the entry is too many hops away or is a notify-neighbor entry, mark any entry we have as bad
          if distance >= 15:
            router.routing_table.mark_bad(network_min, network_max)
          # otherwise have the table consider a new entry based on this tuple
          else:
            router.routing_table.consider(RoutingTableEntry(extended_network=extended_network,
                                                            network_min=network_min,
                                                            network_max=network_max,
                                                            distance=distance + 1,
                                                            port=rx_port,
                                                            next_network=sender_network,
                                                            next_node=sender_node))
        
      elif datagram.ddp_type != self.RTMP_DDP_TYPE_REQUEST or not datagram.data:
        
        continue
        
      elif datagram.data[0] == self.RTMP_FUNC_REQUEST:
        
        # IA 5-23: no case for if port is not connected to an AppleTalk network or its port range contains 0
        if not rx_port.is_appletalk_network(): continue
        if 0 in (rx_port.network_min, rx_port.network_max): continue
        
        if datagram.hop_count != 0: continue  # we have to send responses out of the same port they came in, no routing
        response_data = struct.pack('>HBB', rx_port.network, 8, rx_port.node)
        if rx_port.port_type == Port.PORT_TYPE_EXTENDED_NETWORK:
          response_data += struct.pack('>HBHB', rx_port.network_min, 0x80, rx_port.network_max, self.RTMP_VERSION)
        router.reply(datagram, rx_port, self.RTMP_DDP_TYPE_DATA, response_data)
        
      elif datagram.data[0] in (self.RTMP_FUNC_RDR_SPLIT_HORIZON, self.RTMP_FUNC_RDR_NO_SPLIT_HORIZON):
        
        # IA 5-17: if we don't know the network number range for an AppleTalk port, don't send routing table through that port
        if 0 in (rx_port.network_min, rx_port.network_max) and rx_port.is_appletalk_network(): continue
        
        split_horizon = True if datagram.data[0] == self.RTMP_FUNC_RDR_SPLIT_HORIZON else False
        for datagram_data in self.make_routing_table_datagram_data(router, rx_port, split_horizon):
          router.reply(datagram, rx_port, self.RTMP_DDP_TYPE_DATA, datagram_data)
    
    self.queue.task_done()
  
  def inbound(self, datagram, rx_port):
    self.queue.put((datagram, rx_port))
