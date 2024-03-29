'''Zone Information Service.'''

from collections import deque
from itertools import chain
import logging
from queue import Queue
import struct
from threading import Thread, Event

from . import ZipService
from .. import Service
from ...datagram import Datagram
from ...router.zone_information_table import ucase


class ZipRespondingService(Service, ZipService):
  '''A Service that implements Zone Information Protocol (ZIP).'''
  
  def __init__(self):
    self.thread = None
    self.queue = Queue()
    self.stop_flag = object()
    self.started_event = Event()
    self.stopped_event = Event()
    self._pending_network_zone_name_set = {}
  
  def start(self, router):
    self.thread = Thread(target=self._run, args=(router,))
    self.thread.start()
    self.started_event.wait()
  
  def stop(self):
    self.queue.put(self.stop_flag)
    self.stopped_event.wait()
  
  def _reply(self, router, datagram):
    
    if len(datagram.data) < 2: return
    func, count = struct.unpack('>BB', datagram.data[:2])
    data = datagram.data[2:]
    
    networks_and_zone_names = deque()
    while len(data) >= 3:
      network_min, zone_name_length = struct.unpack('>HB', data[:3])
      zone_name = data[3:3 + zone_name_length]
      if len(zone_name) != zone_name_length: break
      data = data[3 + zone_name_length:]
      if zone_name_length == 0: continue
      networks_and_zone_names.append((network_min, zone_name))
    if not networks_and_zone_names: return
    
    network_min_to_network_max = {}
    for entry in router.routing_table:
      network_min_to_network_max[entry.network_min] = entry.network_max
    
    if func == self.ZIP_FUNC_REPLY:
      for network_min, zone_name in networks_and_zone_names:
        try:
          network_max = network_min_to_network_max[network_min]
        except KeyError:
          logging.warning('%s ZIP reply refers to a network range (starting with %d) with which we are not familiar', str(router), 
                          network_min)
        else:
          try:
            router.zone_information_table.add_networks_to_zone(zone_name, network_min, network_max)
          except ValueError as e:
            logging.warning("%s ZIP reply couldn't be added to zone information table: %s", str(router), e.args[0])
    elif func == self.ZIP_FUNC_EXT_REPLY:
      #TODO this code is fragile and I do not like it
      network_min = None
      for network_min, zone_name in networks_and_zone_names:
        if network_min not in self._pending_network_zone_name_set: self._pending_network_zone_name_set[network_min] = set()
        self._pending_network_zone_name_set[network_min].add(zone_name)
      if network_min is not None and len(self._pending_network_zone_name_set.get(network_min, ())) >= count and count >= 1:
        for zone_name in self._pending_network_zone_name_set.pop(network_min):
          try:
            network_max = network_min_to_network_max[network_min]
          except KeyError:
            logging.warning('%s ZIP reply refers to a network range (starting with %d) with which we are not familiar', str(router),
                            network_min)
          else:
            try:
              router.zone_information_table.add_networks_to_zone(zone_name, network_min, network_max)
            except ValueError as e:
              logging.warning("%s ZIP reply couldn't be added to zone information table: %s", str(router), e.args[0])
  
  @classmethod
  def _query(cls, router, datagram, rx_port):
    if len(datagram.data) < 4: return
    network_count = datagram.data[1]
    if len(datagram.data) != (network_count * 2) + 2: return
    # in imitation of AppleTalk Internet Router, we only respond with extended replies even if a regular reply would fit
    # we also give one list per requested network even if the requested networks are in the same range and the lists are the same;
    # that is, if the sender requests zones for networks 3 and 4 and there is a zones list for networks 3-5, we will reply with the
    # zone list for network 3 twice... seems silly, but this is how ATIR does it so *shrug*
    for network_idx in range(network_count):
      requested_network = struct.unpack('>H', datagram.data[(network_idx * 2) + 2:(network_idx * 2) + 4])[0]
      entry, _ = router.routing_table.get_by_network(requested_network)
      if entry is None: continue
      try:
        zone_names = router.zone_information_table.zones_in_network_range(entry.network_min)
      except ValueError:
        continue
      datagram_data = deque()
      datagram_data_length = 0
      for zone_name in chain(zone_names, (None,)):
        list_item = None if zone_name is None else struct.pack('>HB', entry.network_min, len(zone_name)) + zone_name
        if list_item is None or datagram_data_length + len(list_item) > Datagram.MAX_DATA_LENGTH - 2:
          router.reply(datagram, rx_port, cls.ZIP_DDP_TYPE, struct.pack('>BB', cls.ZIP_FUNC_EXT_REPLY,
                                                                        len(zone_names)) + b''.join(datagram_data))
          datagram_data = deque()
          datagram_data_length = 0
        if list_item is not None:
          datagram_data.append(list_item)
          datagram_data_length += len(list_item)
  
  @classmethod
  def _get_net_info(cls, router, datagram, rx_port):
    if 0 in (rx_port.network, rx_port.network_min, rx_port.network_max): return
    if len(datagram.data) < 7: return
    if datagram.data[1:6] != b'\0\0\0\0\0': return
    given_zone_name = datagram.data[7:7 + datagram.data[6]]
    given_zone_name_ucase = ucase(given_zone_name)
    flags = cls.ZIP_GETNETINFO_ZONE_INVALID | cls.ZIP_GETNETINFO_ONLY_ONE_ZONE
    default_zone_name = None
    number_of_zones = 0
    multicast_address = b''
    try:
      zone_names = router.zone_information_table.zones_in_network_range(rx_port.network_min, rx_port.network_max)
    except ValueError as e:
      logging.warning("%s couldn't get zone names in port network range for GetNetInfo: %s", router, e.args[0])
      return
    for zone_name in zone_names:
      number_of_zones += 1
      if default_zone_name is None:
        # zones_in_network_range returns the default zone first
        default_zone_name = zone_name
        multicast_address = rx_port.multicast_address(zone_name)
      if ucase(zone_name) == given_zone_name_ucase:
        flags &= ~cls.ZIP_GETNETINFO_ZONE_INVALID
        multicast_address = rx_port.multicast_address(zone_name)
      if number_of_zones > 1:
        flags &= ~cls.ZIP_GETNETINFO_ONLY_ONE_ZONE
        if not flags & cls.ZIP_GETNETINFO_ZONE_INVALID: break
    if number_of_zones == 0: return
    if not multicast_address: flags |= cls.ZIP_GETNETINFO_USE_BROADCAST
    reply_data = b''.join((
      struct.pack('>BBHHB', cls.ZIP_FUNC_GETNETINFO_REPLY, flags, rx_port.network_min, rx_port.network_max, len(given_zone_name)),
      given_zone_name,
      struct.pack('>B', len(multicast_address)),
      multicast_address,
      struct.pack('>B', len(default_zone_name)) if flags & cls.ZIP_GETNETINFO_ZONE_INVALID else b'',
      default_zone_name if flags & cls.ZIP_GETNETINFO_ZONE_INVALID else b''))
    router.reply(datagram, rx_port, cls.ZIP_DDP_TYPE, reply_data)
  
  @classmethod
  def _get_my_zone(cls, router, datagram, rx_port):
    _, _, tid, _, _, _ = struct.unpack('>BBHBBH', datagram.data)
    entry, _ = router.routing_table.get_by_network(datagram.source_network)
    if entry is None: return
    try:
      zone_name = next(iter(router.zone_information_table.zones_in_network_range(entry.network_min)), None)
    except ValueError:
      return
    if not zone_name: return
    router.reply(datagram, rx_port, cls.ATP_DDP_TYPE, struct.pack('>BBHBBHB',
                                                                  cls.ATP_FUNC_TRESP | cls.ATP_EOM,
                                                                  0,
                                                                  tid,
                                                                  0,
                                                                  0,
                                                                  1,
                                                                  len(zone_name)) + zone_name)
  
  @classmethod
  def _get_zone_list(cls, router, datagram, rx_port, local=False):
    _, _, tid, _, _, start_index = struct.unpack('>BBHBBH', datagram.data)
    if local:
      try:
        zone_iter = iter(router.zone_information_table.zones_in_network_range(rx_port.network_min, rx_port.network_max))
      except ValueError as e:
        logging.warning("%s couldn't get zone names in port network range for GetLocalZones: %s", router, e.args[0])
        return
    else:
      zone_iter = iter(router.zone_information_table.zones())
    for _ in range(start_index - 1): next(zone_iter, None)  # skip over start_index-1 entries (index is 1-relative)
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
    router.reply(datagram, rx_port, cls.ATP_DDP_TYPE, struct.pack('>BBHBBH',
                                                                  cls.ATP_FUNC_TRESP | cls.ATP_EOM,
                                                                  0,
                                                                  tid,
                                                                  last_flag,
                                                                  0,
                                                                  num_zones) + b''.join(zone_list))
  
  def _run(self, router):
    self.started_event.set()
    while True:
      item = self.queue.get()
      if item is self.stop_flag: break
      datagram, rx_port = item
      if datagram.ddp_type == self.ZIP_DDP_TYPE:
        if not datagram.data: continue
        if datagram.data[0] in (self.ZIP_FUNC_REPLY, self.ZIP_FUNC_EXT_REPLY):
          self._reply(router, datagram)
        elif datagram.data[0] == self.ZIP_FUNC_QUERY:
          self._query(router, datagram, rx_port)
        elif datagram.data[0] == self.ZIP_FUNC_GETNETINFO_REQUEST:
          self._get_net_info(router, datagram, rx_port)
      elif datagram.ddp_type == self.ATP_DDP_TYPE:
        if len(datagram.data) != 8: continue
        control, bitmap, _, func, zero, _ = struct.unpack('>BBHBBH', datagram.data)
        if control != self.ATP_FUNC_TREQ or bitmap != 1 or zero != 0: continue
        if func == self.ZIP_ATP_FUNC_GETMYZONE:
          self._get_my_zone(router, datagram, rx_port)
        elif func == self.ZIP_ATP_FUNC_GETZONELIST:
          self._get_zone_list(router, datagram, rx_port, local=False)
        elif func == self.ZIP_ATP_FUNC_GETLOCALZONES:
          self._get_zone_list(router, datagram, rx_port, local=True)
    self.stopped_event.set()
  
  def inbound(self, datagram, rx_port):
    self.queue.put((datagram, rx_port))
