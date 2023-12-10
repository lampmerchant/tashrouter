'''Port that connects to LocalTalk via TashTalk on a serial port.'''

from queue import Queue, Empty
from threading import Thread, Event

import serial

from . import LocalTalkPort, FcsCalculator
from ...netlog import log_localtalk_frame_inbound, log_localtalk_frame_outbound


class TashTalkPort(LocalTalkPort):
  '''Port that connects to LocalTalk via TashTalk on a serial port.'''
  
  SERIAL_TIMEOUT = 0.25  # seconds
  
  def __init__(self, serial_port, network=0):
    super().__init__(network=network, respond_to_enq=False)
    self._serial_port = serial_port
    self._serial_obj = serial.Serial(port=serial_port, baudrate=1000000, rtscts=True, timeout=None)
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
    return self._serial_port.removeprefix('/dev/')
  
  __str__ = short_str
  __repr__ = short_str
  
  def start(self, router):
    super().start(router)
    self._writer_queue.put(b''.join((
      b'\0' * 1024,  # make sure TashTalk is in a known state, first of all
      b'\x02' + (b'\0' * 32),  # set node IDs bitmap to zeroes so we don't respond to any RTSes or ENQs yet
      b'\x03\0',  # turn off optional TashTalk features
    )))
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
  
  def send_packet(self, packet_data):
    fcs = FcsCalculator()
    fcs.feed(packet_data)
    log_localtalk_frame_outbound(packet_data, self)
    self._writer_queue.put(b''.join((b'\x01', packet_data, bytes((fcs.byte1(), fcs.byte2())))))
  
  def set_node_id(self, node):
    self._writer_queue.put(self.set_node_address_cmd(node))
    super().set_node_id(node)
  
  @staticmethod
  def set_node_address_cmd(desired_node_address):
    if not 1 <= desired_node_address <= 254: raise ValueError('node address %d not between 1 and 254' % desired_node_address)
    retval = bytearray(33)
    retval[0] = 0x02
    byte, bit = divmod(desired_node_address, 8)
    retval[byte + 1] = 1 << bit
    return bytes(retval)
  
  def _reader_run(self):
    self._reader_started_event.set()
    fcs = FcsCalculator()
    buf = bytearray(605)
    buf_ptr = 0
    escaped = False
    while not self._reader_stop_requested:
      for byte in self._serial_obj.read(self._serial_obj.in_waiting or 1):
        if not escaped and byte == 0x00:
          escaped = True
          continue
        elif escaped:
          escaped = False
          if byte == 0xFF:  # literal 0x00 byte
            byte = 0x00
          else:
            if byte == 0xFD and fcs.is_okay() and buf_ptr >= 5:
              data = bytes(buf[:buf_ptr - 2])
              log_localtalk_frame_inbound(data, self)
              self.inbound_packet(data)
            fcs.reset()
            buf_ptr = 0
            continue
        if buf_ptr < len(buf):
          fcs.feed_byte(byte)
          buf[buf_ptr] = byte
          buf_ptr += 1
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
