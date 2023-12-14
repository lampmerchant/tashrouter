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
      
      common_data = b''.join((struct.pack('>BHBBBB', nbp_id, req_network, req_node, req_socket, 0, len(object_field)),
                              object_field,
                              struct.pack('>B', len(type_field)),
                              type_field,
                              struct.pack('>B', len(zone_field)),
                              zone_field))
      lkup_data = struct.pack('>B', (self.NBP_CTRL_LKUP << 4) | 1) + common_data
      fwdreq_data = struct.pack('>B', (self.NBP_CTRL_FWDREQ << 4) | 1) + common_data
      
      if func == self.NBP_CTRL_BRRQ:
        
        # if zone is *, try to sub in the zone name associated with the nonextended network whence the BrRq comes
        if zone_field == b'*':
          if rx_port.extended_network: continue  # BrRqs from extended networks must provide zone name
          if rx_port.network:
            entry, _ = router.routing_table.get_by_network(rx_port.network)
            if entry:
              try:
                zones = list(router.zone_information_table.zones_in_network_range(entry.network_min))
              except ValueError:
                pass
              else:
                if len(zones) == 1: zone_field = zones[0]  # there should not be more than one zone
        
        # if zone is still *, just broadcast a LkUp on the requesting network and call it done
        if zone_field == b'*':
          rx_port.send(0x0000, 0xFF, Datagram(hop_count=0,
                                              destination_network=0x0000,
                                              source_network=rx_port.network,
                                              destination_node=0xFF,
                                              source_node=rx_port.node,
                                              destination_socket=self.NBP_SAS,
                                              source_socket=self.NBP_SAS,
                                              ddp_type=self.NBP_DDP_TYPE,
                                              data=lkup_data))
        # we know the zone, so multicast LkUps to directly-connected networks and send FwdReqs to non-directly-connected ones
        else:
          entries = set(router.routing_table.get_by_network(network)
                        for network in router.zone_information_table.networks_in_zone(zone_field))
          entries.discard((None, None))
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
                                                        data=lkup_data))
            else:
              router.route(Datagram(hop_count=0,
                                    destination_network=entry.network_min,
                                    source_network=0,
                                    destination_node=0x00,
                                    source_node=0,
                                    destination_socket=self.NBP_SAS,
                                    source_socket=self.NBP_SAS,
                                    ddp_type=self.NBP_DDP_TYPE,
                                    data=fwdreq_data))
        
      elif func == self.NBP_CTRL_FWDREQ:
        
        entry, _ = router.routing_table.get_by_network(datagram.destination_network)
        if entry is None or entry.distance != 0: continue  # FwdReq thinks we're directly connected to this network but we're not
        entry.port.multicast(zone_field, Datagram(hop_count=0,
                                                  destination_network=0x0000,
                                                  source_network=entry.port.network,
                                                  destination_node=0xFF,
                                                  source_node=entry.port.node,
                                                  destination_socket=self.NBP_SAS,
                                                  source_socket=self.NBP_SAS,
                                                  ddp_type=self.NBP_DDP_TYPE,
                                                  data=lkup_data))
    
    self.stopped_event.set()
  
  def inbound(self, datagram, rx_port):
    self.queue.put((datagram, rx_port))
