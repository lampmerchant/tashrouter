'''Port base class.'''

from .. import Port


class AppleTalkPort(Port):
  '''An abstraction of a router port connected to an AppleTalk network.'''
  
  extended_network: bool
  network: int
  node: int
  network_min: int
  network_max: int
  
  def unicast(self, network, node, datagram):
    '''Send a Datagram to a single address over this Port.'''
    raise NotImplementedError('subclass must override "unicast" method')
  
  def broadcast(self, datagram):
    '''Broadcast a Datagram over this Port.'''
    raise NotImplementedError('subclass must override "broadcast" method')
  
  def multicast(self, zone_name, datagram):
    '''Multicast a Datagram to a zone over this Port.'''
    raise NotImplementedError('subclass must override "multicast" method')
  
  def set_network_range(self, network_min, network_max):
    '''Set this Port's network range.'''
    raise NotImplementedError('subclass must override "set_network_range" method')
  
  @staticmethod
  def multicast_address(zone_name):
    '''Return the multicast address for the given zone.'''
    raise NotImplementedError('subclass must override "multicast_address" method')
