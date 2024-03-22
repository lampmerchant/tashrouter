'''Port driver for EtherTalk using TUN/TAP.'''

from fcntl import ioctl
import os
from queue import Queue
from select import select
import struct
from threading import Thread, Event

from . import EtherTalkPort


class TapPort(EtherTalkPort):
  '''Port driver for EtherTalk using TUN/TAP.'''
  
  SELECT_TIMEOUT = 0.25  # seconds
  
  TUNSETIFF = 0x400454CA
  IFF_TAP = 0x0002
  IFF_NO_PI = 0x1000
  
  def __init__(self, tap_name, hw_addr, **kwargs):
    super().__init__(hw_addr, **kwargs)
    self._reader_thread = None
    self._reader_started_event = Event()
    self._reader_stop_requested = False
    self._reader_stopped_event = Event()
    self._tap_name = tap_name
    self._fp = None
    self._writer_thread = None
    self._writer_started_event = Event()
    self._writer_stop_flag = object()
    self._writer_stopped_event = Event()
    self._writer_queue = Queue()
  
  def short_str(self):
    return self._tap_name
  
  __str__ = short_str
  __repr__ = short_str
  
  def start(self, router):
    super().start(router)
    self._fp = os.open('/dev/net/tun', os.O_RDWR)
    ioctl(self._fp, self.TUNSETIFF, struct.pack('16sH22x', self._tap_name.encode('ascii') or b'', self.IFF_TAP | self.IFF_NO_PI))
    self._reader_thread = Thread(target=self._reader_run)
    self._reader_thread.start()
    self._writer_thread = Thread(target=self._writer_run)
    self._writer_thread.start()
    self._reader_started_event.wait()
    self._writer_started_event.wait()
  
  def stop(self):
    self._reader_stop_requested = True
    self._writer_queue.put(self._writer_stop_flag)
    self._reader_stopped_event.wait()
    self._writer_stopped_event.wait()
    os.close(self._fp)
    super().stop()
  
  def send_frame(self, frame_data):
    self._writer_queue.put(frame_data)
  
  def _reader_run(self):
    self._reader_started_event.set()
    while not self._reader_stop_requested:
      rlist, _, _ = select((self._fp,), (), (), self.SELECT_TIMEOUT)
      if self._fp not in rlist: continue
      self.inbound_frame(os.read(self._fp, 65535))
    self._reader_stopped_event.set()
  
  def _writer_run(self):
    self._writer_started_event.set()
    while True:
      frame_data = self._writer_queue.get()
      if frame_data is self._writer_stop_flag: break
      select((), (self._fp,), ())
      os.write(self._fp, frame_data)
    self._writer_stopped_event.set()
