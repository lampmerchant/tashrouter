'''RoutingTable aging service.'''

from threading import Thread, Event

from . import Service


class RoutingTableAgingService(Service):
  '''A Service which ages the Router's RoutingTable on a regular basis.'''
  
  DEFAULT_TIMEOUT = 20  # seconds
  
  def __init__(self, timeout=DEFAULT_TIMEOUT):
    self.timeout = timeout
    self.thread = None
    self.started_event = Event()
    self.stop_requested_event = Event()
    self.stopped_event = Event()
  
  def start(self, router):
    self.thread = Thread(target=self._run, args=(router,))
    self.thread.start()
    self.started_event.wait()
  
  def stop(self):
    self.stop_requested_event.set()
    self.stopped_event.wait()
  
  def _run(self, router):
    self.started_event.set()
    while True:
      if self.stop_requested_event.wait(timeout=self.timeout): break
      router.routing_table.age()
    self.stopped_event.set()
  
  def inbound(self, datagram, rx_port):
    pass
