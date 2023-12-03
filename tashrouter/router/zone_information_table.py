'''Zone Information Table (ZIT) class and associated things.'''


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
  
  def __init__(self):
    self._network_to_zone_name_set = {}
    self._zone_name_to_network_set = {}
    self._ucased_zone_name_to_zone_name = {}
  
  def add_networks(self, zone_name, networks):
    '''Add networks to a zone, adding the zone if it isn't in the table.'''
    ucased_zone_name = ucase(zone_name)
    if ucased_zone_name in self._ucased_zone_name_to_zone_name:
      zone_name = self._ucased_zone_name_to_zone_name[ucased_zone_name]
      networks = set(networks)
      self._zone_name_to_network_set[zone_name] |= networks
    else:
      self._ucased_zone_name_to_zone_name[ucased_zone_name] = zone_name
      networks = self._zone_name_to_network_set[zone_name] = set(networks)
    for network in networks:
      if network in self._network_to_zone_name_set:
        self._network_to_zone_name_set[network].add(zone_name)
      else:
        self._network_to_zone_name_set[network] = set((zone_name,))
  
  def remove_networks(self, zone_name, networks):
    '''Remove networks from a zone, removing the zone if its network set is empty.'''
    ucased_zone_name = ucase(zone_name)
    zone_name = self._ucased_zone_name_to_zone_name.get(ucased_zone_name)
    if not zone_name: return
    s = self._zone_name_to_network_set[zone_name]
    networks = set(networks)
    s -= networks
    if not s:
      self._zone_name_to_network_set.pop(zone_name)
      self._ucased_zone_name_to_zone_name.pop(ucased_zone_name)
    for network in networks:
      s = self._network_to_zone_name_set[network]
      s.discard(zone_name)
      if not s: self._network_to_zone_name_set.pop(network)
  
  def zones(self):
    '''Return the zones in this ZIT.'''
    return self._zone_name_to_network_set.keys()
  
  def zones_and_networks(self):
    '''Yield (zone name, tuple of network numbers) tuples for each zone in this ZIT.'''
    for zone_name, network_set in self._zone_name_to_network_set.items(): yield zone_name, tuple(network_set)
  
  def networks_and_zones(self):
    '''Yield (network number, tuple of zone names) tuples for each network in this ZIT.'''
    for network, zone_name_set in self._network_to_zone_name_set.items(): yield network, tuple(zone_name_set)
  
  def zones_in_network(self, network):
    '''Yield the names of all zones in the network with the given number.'''
    try:
      for zone_name in self._network_to_zone_name_set[network]: yield zone_name
    except KeyError:
      return
  
  def zones_in_network_range(self, network_min, network_max):
    '''Yield the names of all zones in the networks inside the given range.'''
    already_yielded = set()
    for network in range(network_min, network_max + 1):
      for zone_name in self._network_to_zone_name_set.get(network, ()):
        if zone_name not in already_yielded:
          yield zone_name
          already_yielded.add(zone_name)
  
  def networks_in_zone(self, zone_name):
    '''Yield the network numbers of all networks in the given zone.'''
    try:
      for network in self._zone_name_to_network_set[self._ucased_zone_name_to_zone_name[ucase(zone_name)]]: yield network
    except KeyError:
      return
