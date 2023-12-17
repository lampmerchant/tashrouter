'''Zone Information Table (ZIT) class and associated things.'''

from collections import deque
import logging
from threading import Lock


ATALK_LCASE = b'abcdefghijklmnopqrstuvwxyz\x88\x8A\x8B\x8C\x8D\x8E\x96\x9A\x9B\x9F\xBE\xBF\xCF'
ATALK_UCASE = b'ABCDEFGHIJKLMNOPQRSTUVWXYZ\xCB\x80\xCC\x81\x82\x83\x84\x85\xCD\x86\xAE\xAF\xCE'


def ucase_char(byte):
  '''Convert a single byte to its uppercase representation using the correspondence table laid out in IA Appendix D.'''
  try:
    return ATALK_UCASE[ATALK_LCASE.index(byte)]
  except ValueError:
    return byte


def ucase(b):
  '''Convert a bytes-like to uppercase using the correspondence table laid out in IA Appendix D.'''
  return bytes(ucase_char(byte) for byte in b)


class ZoneInformationTable:
  '''Zone Information Table (ZIT).'''
  
  def __init__(self, router):
    self._router = router
    self._network_min_to_network_max = {}
    self._network_min_to_zone_name_set = {}
    self._network_min_to_default_zone_name = {}
    self._zone_name_to_network_min_set = {}
    self._ucased_zone_name_to_zone_name = {}
    self._lock = Lock()
  
  def _check_range(self, network_min, network_max=None):
    looked_up_network_max = self._network_min_to_network_max.get(network_min)
    if network_max is None:
      if looked_up_network_max is None:
        raise ValueError('network range %d-? does not exist' % network_min)
      else:
        return looked_up_network_max
    elif looked_up_network_max == network_max:  # if network range exists as given
      return network_max
    elif looked_up_network_max is not None:
      raise ValueError('network range %d-%d overlaps %d-%d' % (network_min, network_max, network_min, looked_up_network_max))
    else:  # check for overlap
      for existing_min, existing_max in self._network_min_to_network_max.items():
        if existing_min > network_max or existing_max < network_min: continue
        raise ValueError('network range %d-%d overlaps %d-%d' % (network_min, network_max, existing_min, existing_max))
      return None
  
  def add_networks_to_zone(self, zone_name, network_min, network_max=None):
    '''Add a range of networks to a zone, adding the zone if it isn't in the table.'''
    
    if network_max and network_max < network_min: raise ValueError('range %d-%d is backwards' % (network_min, network_max))
    ucased_zone_name = ucase(zone_name)
    
    with self._lock:
      
      if ucased_zone_name in self._ucased_zone_name_to_zone_name:
        zone_name = self._ucased_zone_name_to_zone_name[ucased_zone_name]
      else:
        self._ucased_zone_name_to_zone_name[ucased_zone_name] = zone_name
        self._zone_name_to_network_min_set[zone_name] = set()
      
      check_range = self._check_range(network_min, network_max)
      if check_range:
        network_max = check_range
        self._network_min_to_zone_name_set[network_min].add(zone_name)
        now_default = False
      else:
        self._network_min_to_network_max[network_min] = network_max
        self._network_min_to_zone_name_set[network_min] = set((zone_name,))
        self._network_min_to_default_zone_name[network_min] = zone_name
        now_default = True
      
      logging.debug('%s adding network range %d-%d to zone %s%s', str(self._router), network_min, network_max,
                    zone_name.decode('mac_roman', 'replace'), ' (now default zone for this range)' if now_default else '')
      self._zone_name_to_network_min_set[zone_name].add(network_min)
  
  def remove_networks(self, network_min, network_max=None):
    '''Remove a range of networks from all zones, removing associated zones if now empty of networks.'''
    if network_max and network_max < network_min: raise ValueError('range %d-%d is backwards' % (network_min, network_max))
    with self._lock:
      network_max = self._check_range(network_min, network_max)
      if not network_max: return
      logging.debug('%s removing network range %d-%d from all zones', str(self._router), network_min, network_max)
      for zone_name in self._network_min_to_zone_name_set[network_min]:
        s = self._zone_name_to_network_min_set[zone_name]
        s.remove(network_min)
        if not s:
          logging.debug('%s removing zone %s because it no longer contains any networks', str(self._router),
                        zone_name.decode('mac_roman', 'replace'))
          self._zone_name_to_network_min_set.pop(zone_name)
          self._ucased_zone_name_to_zone_name.pop(ucase(zone_name))
      self._network_min_to_default_zone_name.pop(network_min)
      self._network_min_to_zone_name_set.pop(network_min)
      self._network_min_to_network_max.pop(network_min)
  
  def zones(self):
    '''Return the zones in this ZIT.'''
    with self._lock:
      return list(self._zone_name_to_network_min_set.keys())
  
  def zones_in_network_range(self, network_min, network_max=None):
    '''Return a deque containing the names of all zones in the given range of networks, default zone name first.'''
    if network_max and network_max < network_min: raise ValueError('range %d-%d is backwards' % (network_min, network_max))
    with self._lock:
      if not self._check_range(network_min, network_max): return deque()
      default_zone_name = self._network_min_to_default_zone_name[network_min]
      retval = deque(zone_name for zone_name in self._network_min_to_zone_name_set[network_min] if zone_name != default_zone_name)
      retval.appendleft(default_zone_name)
    return retval
  
  def networks_in_zone(self, zone_name):
    '''Return a deque containing the network numbers of all networks in the given zone.'''
    with self._lock:
      zone_name = self._ucased_zone_name_to_zone_name.get(ucase(zone_name))
      if zone_name is None: return deque()
      retval = deque()
      for network_min in self._zone_name_to_network_min_set[zone_name]:
        retval.extend(range(network_min, self._network_min_to_network_max[network_min] + 1))
    return retval
