'''Name Information Service.'''

from queue import Queue
import struct
from threading import Thread, Event

from . import Service
from ..datagram import Datagram


class NameInformationService(Service):
  '''A Service that implements Name Binding Protocol (NBP).'''
  
  NBP_SAS = 2
  NBP_DDP_TYPE = 2
  
  NBP_CTRL_BRRQ = 1
  NBP_CTRL_LKUP = 2
  NBP_CTRL_LKUP_REPLY = 3
  NBP_CTRL_FWDREQ = 4
  
  MAX_FIELD_LEN = 32
  
  def __init__(self):
    self.thread = None
    self.queue = Queue()
    self.stop_flag = object()
    self.started_event = Event()
    self.stopped_event = Event()
  
  def start(self, router):
    self.thread = Thread(target=self._run, args=(router,))
    self.thread.start()
    self.started_event.wait()
  
  def stop(self):
    self.queue.put(self.stop_flag)
    self.stopped_event.wait()
  
  def _run(self, router):
    
    self.started_event.set()
    
    while True:
      
      item = self.queue.get()
      if item is self.stop_flag: break
      datagram, rx_port = item
      
      if datagram.ddp_type != self.NBP_DDP_TYPE: continue
      if len(datagram.data) < 12: continue
      func_tuple_count, nbp_id, req_network, req_node, req_socket, _, object_field = struct.unpack('>BBHBBBB', datagram.data[:8])
      func = func_tuple_count >> 4
      tuple_count = func_tuple_count & 0xF
      if tuple_count != 1 or func not in (self.NBP_CTRL_BRRQ, self.NBP_CTRL_FWDREQ): continue
      if object_field < 1 or object_field > self.MAX_FIELD_LEN: continue
      if len(datagram.data) < 8 + object_field: continue
      type_field = datagram.data[8 + object_field]
      if type_field < 1 or type_field > self.MAX_FIELD_LEN: continue
      if len(datagram.data) < 9 + object_field + type_field: continue
      zone_field = datagram.data[9 + object_field + type_field]
      if zone_field > self.MAX_FIELD_LEN: continue
      if len(datagram.data) < 10 + object_field + type_field + zone_field: continue
      zone_field = datagram.data[10 + object_field + type_field:10 + object_field + type_field + zone_field] or b'*'
      type_field = datagram.data[9 + object_field:9 + object_field + type_field]
      object_field = datagram.data[8:8 + object_field]
      
      if func == self.NBP_CTRL_BRRQ:
        
        if zone_field == b'*':
          if rx_port.extended_network: continue  # BrRqs from extended networks must provide zone name
          if rx_port.network:
            zones = list(router.zone_information_table.zones_in_network(rx_port.network))
            if len(zones) == 1:
              zone_field = zones[0]
            elif len(zones) > 1:
              continue  # this should be impossible
        
        entries = set(router.routing_table.get_by_network(network)
                      for network in router.zone_information_table.networks_in_zone(zone_field))
        entries.discard(None)
        for entry, _ in entries:
          if entry.distance == 0:
            entry.port.multicast(zone_field, Datagram(hop_count=0,
                                                      destination_network=0x0000,
                                                      source_network=entry.port.network,
                                                      destination_node=0xFF,
                                                      source_node=entry.port.node,
                                                      destination_socket=self.NBP_SAS,
                                                      source_socket=self.NBP_SAS,
                                                      ddp_type=self.NBP_DDP_TYPE,
                                                      data=b''.join((struct.pack('>BBHBBBB',
                                                                                 (self.NBP_CTRL_LKUP << 4) | 1,
                                                                                 nbp_id,
                                                                                 req_network,
                                                                                 req_node,
                                                                                 req_socket,
                                                                                 0,
                                                                                 len(object_field)),
                                                                     object_field,
                                                                     struct.pack('>B', len(type_field)),
                                                                     type_field,
                                                                     struct.pack('>B', len(zone_field)),
                                                                     zone_field))))
          else:
            router.route(Datagram(hop_count=0,
                                  destination_network=entry.network_min,
                                  source_network=0,
                                  destination_node=0x00,
                                  source_node=0,
                                  destination_socket=self.NBP_SAS,
                                  source_socket=self.NBP_SAS,
                                  ddp_type=self.NBP_DDP_TYPE,
                                  data=b''.join((struct.pack('>BBHBBBB',
                                                             (self.NBP_CTRL_FWDREQ << 4) | 1,
                                                             nbp_id,
                                                             req_network,
                                                             req_node,
                                                             req_socket,
                                                             0,
                                                             len(object_field)),
                                                 object_field,
                                                 struct.pack('>B', len(type_field)),
                                                 type_field,
                                                 struct.pack('>B', len(zone_field)),
                                                 zone_field))))
        
      elif func == self.NBP_CTRL_FWDREQ:
        
        rx_port.multicast(zone_field, Datagram(hop_count=0,
                                               destination_network=0x0000,
                                               source_network=rx_port.network,
                                               destination_node=0xFF,
                                               source_node=rx_port.node,
                                               destination_socket=self.NBP_SAS,
                                               source_socket=self.NBP_SAS,
                                               ddp_type=self.NBP_DDP_TYPE,
                                               data=b''.join((struct.pack('>BBHBBBB',
                                                                          (self.NBP_CTRL_LKUP << 4) | 1,
                                                                          nbp_id,
                                                                          req_network,
                                                                          req_node,
                                                                          req_socket,
                                                                          0,
                                                                          len(object_field)),
                                                              object_field,
                                                              struct.pack('>B', len(type_field)),
                                                              type_field,
                                                              struct.pack('>B', len(zone_field)),
                                                              zone_field))))
    
    self.stopped_event.set()
  
  def inbound(self, datagram, rx_port):
    self.queue.put((datagram, rx_port))
