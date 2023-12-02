'''Service base class.'''


class Service:
  '''A service that lives on a router and sends/receives on a static socket.
  
  This class does not extend Thread because it may have multiple threads according to the implementer's design.
  '''
  
  def start(self, router):
    '''Starts the Service connected to a given router.'''
    raise NotImplementedError('subclass must override "start" method')
  
  def stop(self):
    '''Stops the Service.'''
    raise NotImplementedError('subclass must override "stop" method')
  
  def inbound(self, datagram, rx_port):
    '''Called when a Datagram comes in over a Port from the Router to which this Service is connected.'''
    raise NotImplementedError('subclass must override "inbound" method')
