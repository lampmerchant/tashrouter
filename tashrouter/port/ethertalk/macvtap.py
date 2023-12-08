'''Port driver for EtherTalk using MACVTAP.'''

import os
from queue import Queue
from select import select
from threading import Thread, Event

from . import EtherTalkPort


# ip link add link eth0 name macvtap0 type macvtap  # this creates /dev/tap3 because third interface
# ip link set dev macvtap0 promisc on  # this is important, otherwise we don't get broadcast frames


class MacvtapPort(EtherTalkPort):
  '''Port driver for EtherTalk using MACVTAP.'''

  SELECT_TIMEOUT = 0.25  # seconds

  def __init__(self, device=None, network_min=0, network_max=0, desired_network=0, desired_node=0):
    #TODO can find via /sys/class/net/macvtap*/ - maybe do this if device is None?
    #TODO more important to get MAC than in a tap, I think
    super().__init__(b'\xDE\xAD\xBE\xEF\xCA\xFE', network_min, network_max, desired_network, desired_node)
    self._reader_thread = None
    self._reader_started_event = Event()
    self._reader_stop_requested = False
    self._reader_stopped_event = Event()
    self._device = device
    self._fp = None
    self._writer_thread = None
    self._writer_started_event = Event()
    self._writer_stop_flag = object()
    self._writer_stopped_event = Event()
    self._writer_queue = Queue()

  def start(self, router):
    super().start(router)
    self._fp = os.open(self._device, os.O_RDWR)
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
      #TODO what's with the 10-byte header?
      self.inbound_frame(os.read(self._fp, 65535)[10:])
    self._reader_stopped_event.set()

  def _writer_run(self):
    self._writer_started_event.set()
    while True:
      frame_data = self._writer_queue.get()
      if frame_data is self._writer_stop_flag: break
      select((), (self._fp,), ())
      #TODO what's with the 10-byte header?
      os.write(self._fp, (b'\0' * 10) + frame_data)
    self._writer_stopped_event.set()
