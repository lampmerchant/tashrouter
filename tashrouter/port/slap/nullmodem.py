'''Port that connects over a null modem cable.'''

from queue import Queue, Empty
from threading import Thread, Event

import serial

from . import SlapPort


class NullModemPort(SlapPort):
  '''Port that connects over a null modem cable.'''
  
  SERIAL_TIMEOUT = 0.25  # seconds
  
  def __init__(self, serial_port, baud_rate):
    super().__init__()
    self._serial_port = serial_port
    self._serial_obj = serial.Serial(port=serial_port, baudrate=baud_rate, timeout=None)
    self._reader_thread = None
    self._reader_started_event = Event()
    self._reader_stop_requested = False
    self._reader_stopped_event = Event()
    self._writer_thread = None
    self._writer_started_event = Event()
    self._writer_queue = Queue()
    self._writer_stop_flag = object()
    self._writer_stopped_event = Event()
  
  def short_str(self):
    return self._serial_port[5:] if self._serial_port.startswith('/dev/') else self._serial_port
  
  __str__ = short_str
  __repr__ = short_str
  
  def start(self, router):
    super().start(router)
    self._reader_thread = Thread(target=self._reader_run)
    self._reader_thread.start()
    self._writer_thread = Thread(target=self._writer_run)
    self._writer_thread.start()
    self._reader_started_event.wait()
    self._writer_started_event.wait()
  
  def stop(self):
    super().stop()
    self._reader_stop_requested = True
    self._writer_queue.put(self._writer_stop_flag)
    self._reader_stopped_event.wait()
    self._writer_stopped_event.wait()
  
  def outgoing_bytes(self, b):
    self._writer_queue.put(b)
  
  def _reader_run(self):
    self._reader_started_event.set()
    while not self._reader_stop_requested:
      self.incoming_bytes(self._serial_obj.read(self._serial_obj.in_waiting or 1))
    self._reader_stopped_event.set()
  
  def _writer_run(self):
    self._writer_started_event.set()
    while True:
      try:
        item = self._writer_queue.get(block=True, timeout=self.SERIAL_TIMEOUT)
      except Empty:
        item = None
      #TODO make sure OS queue isn't overflowing?
      self._serial_obj.cancel_read()
      if item is self._writer_stop_flag: break
      if item: self._serial_obj.write(item)
    self._writer_stopped_event.set()
