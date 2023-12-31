'''Echo service.'''

from queue import Queue
from threading import Thread, Event

from . import Service


class EchoService(Service):
  '''A Service which implements AppleTalk Echo Protocol (AEP).'''
  
  ECHO_SAS = 4
  ECHO_DDP_TYPE = 4
  
  ECHO_FUNC_REQUEST_BYTE = b'\x01'
  ECHO_FUNC_REPLY_BYTE = b'\x02'
  
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
  
  def _run(self, router):
    self.started_event.set()
    while True:
      item = self.queue.get()
      if item is self.stop_flag: break
      datagram, rx_port = item
      if datagram.ddp_type != self.ECHO_DDP_TYPE: continue
      if not datagram.data: continue
      if datagram.data[0:1] != self.ECHO_FUNC_REQUEST_BYTE: continue
      router.reply(datagram, rx_port, self.ECHO_DDP_TYPE, self.ECHO_FUNC_REPLY_BYTE + datagram.data[1:])
    self.stopped_event.set()
  
  def inbound(self, datagram, rx_port):
    self.queue.put((datagram, rx_port))
