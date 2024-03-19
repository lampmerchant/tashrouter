'''RoutingTable sending Service.'''

from queue import Queue, Empty
from threading import Thread, Event

from . import RtmpService
from .. import Service
from ...datagram import Datagram


class RtmpSendingService(Service, RtmpService):
  '''A Service which sends RTMP Datagrams containing the Router's RoutingTable to its Ports on a regular basis.'''
  
  DEFAULT_TIMEOUT = 10  # seconds
  
  def __init__(self, timeout=DEFAULT_TIMEOUT):
    self.timeout = timeout
    self.thread = None
    self.started_event = Event()
    self.queue = Queue()
    self.stop_flag = object()
    self.force_send_flag = object()
  
  def start(self, router):
    self.thread = Thread(target=self._run, args=(router,))
    self.thread.start()
    self.started_event.wait()
  
  def stop(self):
    self.queue.put(self.stop_flag)
    self.queue.join()
  
  def _run(self, router):
    self.started_event.set()
    while True:
      try:
        item = self.queue.get(timeout=self.timeout)
      except Empty:
        item = None
      if item is self.stop_flag: break
      for port in router.ports:
        if 0 in (port.node, port.network): continue
        for datagram_data in self.make_routing_table_datagram_data(router, port):
          port.broadcast(Datagram(hop_count=0,
                                  destination_network=0x0000,
                                  source_network=port.network,
                                  destination_node=0xFF,
                                  source_node=port.node,
                                  destination_socket=self.RTMP_SAS,
                                  source_socket=self.RTMP_SAS,
                                  ddp_type=self.RTMP_DDP_TYPE_DATA,
                                  data=datagram_data))
      if item is not None: self.queue.task_done()
    self.queue.task_done()
  
  def inbound(self, datagram, rx_port):
    pass
  
  def force_send(self):
    '''Force this service to immediately send an RTMP Datagram for testing purposes.'''
    self.queue.put(self.force_send_flag)
    self.queue.join()
