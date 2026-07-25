'''Port base class.'''


class Port:
  '''An abstraction of a router port, a connection to a physical network.
  
  Note that a Port should only deliver Datagrams addressed to it (and broadcast Datagrams) to its Router.
  
  This class does not extend Thread because it may have multiple threads according to the implementer's design.
  '''
  
  def short_str(self):
    '''Return a short string representation of this Port.'''
    raise NotImplementedError('subclass must override "short_str" method')
  
  def start(self, router):
    '''Start this Port running.'''
    raise NotImplementedError('subclass must override "start" method')
  
  def stop(self):
    '''Stop this Port from running.'''
    raise NotImplementedError('subclass must override "stop" method')
