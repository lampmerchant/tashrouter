'''Zone Information Service.'''

from collections import deque
from itertools import chain
from queue import Queue
import struct
from threading import Thread, Event

from . import Service
from ..datagram import Datagram, ddp_checksum


class ZoneInformationService(Service):
  '''A Service that implements Zone Information Protocol (ZIP).'''
  
  ZIP_SAS = 6
  ZIP_DDP_TYPE = 6
  
  ZIP_FUNC_QUERY = 1
  ZIP_FUNC_REPLY = 2
  ZIP_FUNC_GETNETINFO_REQUEST = 5
  ZIP_FUNC_GETNETINFO_REPLY = 6
  ZIP_FUNC_NOTIFY = 7
  ZIP_FUNC_EXT_REPLY = 8
  
  ZIP_ATP_FUNC_GETMYZONE = 7
  ZIP_ATP_FUNC_GETZONELIST = 8
  ZIP_ATP_FUNC_GETLOCALZONES = 9
  
  ATP_DDP_TYPE = 3
  
  ATP_FUNC_TREQ = 0b01000000
  ATP_FUNC_TRESP = 0b10000000
  ATP_FUNC_TREL = 0b11000000
  ATP_EOM = 0b00010000
  
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
  
  @staticmethod
  def _networks_zone_list(zit, networks):
    for network in networks:
      for zone_name in zit.zones_in_network(network):
        yield network, struct.pack('>HB', network, len(zone_name)) + zone_name
  
  def _query(self, router, datagram):
    if len(datagram.data) < 4: return
    network_count = datagram.data[1]
    if len(datagram.data) != (network_count * 2) + 2: return
    networks = [struct.unpack('>H', datagram.data[(i * 2) + 2:(i * 2) + 4]) for i in range(network_count)]
    networks_zone_list = list(self._networks_zone_list(router.zone_information_table, networks))
    networks_zone_list_byte_length = sum(len(list_item) for network, list_item in networks_zone_list)
    if networks_zone_list_byte_length + 2 <= Datagram.MAX_DATA_LENGTH:
      router.route(Datagram(hop_count=0,
                            destination_network=datagram.source_network,
                            source_network=0,
                            destination_node=datagram.source_node,
                            source_node=0,
                            destination_socket=datagram.source_socket,
                            source_socket=datagram.destination_socket,
                            ddp_type=self.ZIP_DDP_TYPE,
                            data=struct.pack('>BB', self.ZIP_FUNC_REPLY, len(networks)) +  #TODO should be len(networks_zone_list)?
                            b''.join(list_item for network, list_item in networks_zone_list)))
    else:
      zone_list_by_network = {}
      for network, list_item in networks_zone_list:
        if network not in zone_list_by_network: zone_list_by_network[network] = deque()
        zone_list_by_network[network].append(list_item)
      for network, zone_list in zone_list_by_network.items():
        datagram_data = deque()
        datagram_data_length = 0
        for list_item in chain(zone_list, (None,)):
          if list_item is None or datagram_data_length + len(list_item) > Datagram.MAX_DATA_LENGTH - 2:
            router.route(Datagram(hop_count=0,
                                  destination_network=datagram.source_network,
                                  source_network=0,
                                  destination_node=datagram.source_node,
                                  source_node=0,
                                  destination_socket=datagram.source_socket,
                                  source_socket=datagram.destination_socket,
                                  ddp_type=self.ZIP_DDP_TYPE,
                                  data=struct.pack('>BB', self.ZIP_FUNC_EXT_REPLY, len(zone_list)) + b''.join(datagram_data)))
          datagram_data.append(list_item)
          datagram_data_length += len(list_item)
  
  def _get_net_info(self, router, datagram):
    if len(datagram.data) < 7: return
    if datagram.data[1:6] != b'\0\0\0\0\0': return
    zone_name = datagram.data[7:7 + datagram.data[6]]
    #TODO write the rest of this
  
  def _get_my_zone(self, router, datagram):
    _, _, tid, _, _, start_index = struct.unpack('>BBHBBH', datagram.data)
    if start_index != 0: return
    zone_name = next(router.zone_information_table.zones_in_network(datagram.source_network), None)
    if not zone_name: return
    router.route(Datagram(hop_count=0,
                          destination_network=datagram.source_network,
                          source_network=0,
                          destination_node=datagram.source_node,
                          source_node=0,
                          destination_socket=datagram.source_socket,
                          source_socket=datagram.destination_socket,
                          ddp_type=self.ATP_DDP_TYPE,
                          data=struct.pack('>BBHBBHB', self.ATP_FUNC_TRESP | self.ATP_EOM, 0, tid, 0, 0, 1, len(zone_name)) +
                          zone_name))
  
  def _get_zone_list(self, router, datagram, local=False):
    _, _, tid, _, _, start_index = struct.unpack('>BBHBBH', datagram.data)
    #TODO what's meant by 'local' anyway
    zone_iter = (router.zone_information_table.zones_in_network(datagram.source_network) if local
                 else iter(router.zone_information_table.zones()))
    for _ in range(start_index - 1): next(zone_iter, None)  # skip over start_index-1 entries (index is 1-relative, I guess)
    last_flag = 0
    zone_list = deque()
    num_zones = 0
    data_length = 8
    while zone_name := next(zone_iter, None):
      if data_length + 1 + len(zone_name) > Datagram.MAX_DATA_LENGTH: break
      zone_list.append(struct.pack('>B', len(zone_name)))
      zone_list.append(zone_name)
      num_zones += 1
      data_length += 1 + len(zone_name)
    else:
      last_flag = 1
    router.route(Datagram(hop_count=0,
                          destination_network=datagram.source_network,
                          source_network=0,
                          destination_node=datagram.source_node,
                          source_node=0,
                          destination_socket=datagram.source_socket,
                          source_socket=datagram.destination_socket,
                          ddp_type=self.ATP_DDP_TYPE,
                          data=struct.pack('>BBHBBH',
                                           self.ATP_FUNC_TRESP | self.ATP_EOM,
                                           0,
                                           tid,
                                           last_flag,
                                           0,
                                           num_zones) + b''.join(zone_list)))
  
  def _run(self, router):
    self.started_event.set()
    while True:
      datagram = self.queue.get()
      if datagram is self.stop_flag: break
      if datagram.ddp_type == self.ZIP_DDP_TYPE:
        if not datagram.data: continue
        if datagram.data[0] == self.ZIP_FUNC_QUERY:
          self._query(router, datagram)
        elif datagram.data[0] == self.ZIP_FUNC_GETNETINFO_REQUEST:
          self._get_net_info(router, datagram)
      elif datagram.ddp_type == self.ATP_DDP_TYPE:
        if len(datagram.data) != 8: continue
        control, bitmap, _, func, zero, _ = struct.unpack('>BBHBBH', datagram.data)
        if control != self.ATP_FUNC_TREQ or bitmap != 1 or zero != 0: continue
        if func == self.ZIP_ATP_FUNC_GETMYZONE:
          self._get_my_zone(router, datagram)
        elif func == self.ZIP_ATP_FUNC_GETZONELIST:
          self._get_zone_list(router, datagram, local=False)
        elif func == self.ZIP_ATP_FUNC_GETLOCALZONES:
          self._get_zone_list(router, datagram, local=True)
    self.stopped_event.set()
  
  def inbound(self, datagram, _):
    self.queue.put(datagram)
