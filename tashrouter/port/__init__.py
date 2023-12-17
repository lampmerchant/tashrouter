'''Port base class.'''


class Port:
  '''An abstraction of a router port, a connection to a physical network.
  
  Note that this covers only the case of a connection to an AppleTalk network, not the "half router" or "backbone network" cases
  detailed in Inside AppleTalk.
  
  Note also that a Port should only deliver Datagrams addressed to it (and broadcast Datagrams) to its Router.
  
  This class does not extend Thread because it may have multiple threads according to the implementer's design.
  '''
  
  network: int
  node: int
  network_min: int
  network_max: int
  extended_network: bool
  
  def short_str(self):
    '''Return a short string representation of this Port.'''
    raise NotImplementedError('subclass must override "short_str" method')
  
  def start(self, router):
    '''Start this Port running.'''
    raise NotImplementedError('subclass must override "start" method')
  
  def stop(self):
    '''Stop this Port from running.'''
    raise NotImplementedError('subclass must override "stop" method')
  
  def send(self, network, node, datagram):
    '''Send a Datagram to an address over this Port.'''
    raise NotImplementedError('subclass must override "send" method')
  
  def multicast(self, zone_name, datagram):
    '''Multicast a Datagram to a zone over this Port.'''
    raise NotImplementedError('subclass must override "multicast" method')
  
  def set_network_range(self, network_min, network_max):
    '''Set this Port's network range according to a seed router.'''
    raise NotImplementedError('subclass must override "set_network_range" method')
  
  @staticmethod
  def multicast_address(zone_name):
    '''Return the multicast address for the given zone.'''
    raise NotImplementedError('subclass must override "multicast_address" method')
