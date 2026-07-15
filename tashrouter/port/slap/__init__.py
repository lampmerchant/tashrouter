'''Superclass for Ports that communicate over a point-to-point line of some kind using Serial Line AppleTalk Protocol (SLAP).'''

from hashlib import sha256

from .. import Port
from ...datagram import Datagram
from ...netlog import log_datagram_inbound, log_datagram_unicast, log_datagram_broadcast, log_datagram_multicast


class SlapPort(Port):
  '''Superclass for Ports that communicate over a point-to-point line of some kind using Serial Line AppleTalk Protocol (SLAP).'''
  
  HASH_CLASS = sha256
  
  BUFFER_SIZE = 603
  
  ESC_BYTE = 0x1B  # ESC
  ESC_START = 0x00  # escape sequence that starts a Datagram
  ESC_END_SHORT = 0x01  # escape sequence that ends a short-form Datagram
  ESC_END_LONG = 0x02  # escape sequence that ends a long-form Datagram
  ESC_ESC = 0xFF  # escape sequence for raw ESC char
  
  def __init__(self):
    self.network = self.node = self.network_min = self.network_max = 0
    self.extended_network = False  #TODO not sure
    self.is_point_to_point = True
    self._router = None
    self._escape = False
    self._hash = None
    self._buffer = None
    self._buffer_idx = 0
  
  def _reset(self):
    self._escape = False
    self._hash = self.HASH_CLASS()
    self._hash_buffer = bytearray(self._hash.digest_size)
    self._buffer_idx = -self._hash.digest_size
    self._buffer = bytearray(self.BUFFER_SIZE)
  
  def start(self, router):
    self._router = router
    self._reset()
  
  def stop(self):
    pass
  
  def _incoming_byte(self, byte):
    if byte == self.ESC_BYTE:
      self._escape = True
      return
    if self._escape:
      self._escape = False
      if byte == self.ESC_START:
        self._reset()
        return
      elif byte == self.ESC_END_SHORT:
        self._complete_short()
        return
      elif byte == self.ESC_END_LONG:
        self._complete_long()
        return
      elif byte == self.ESC_ESC:
        byte = self.ESC_BYTE
      else:
        return
    if self._buffer_idx < 0:
      self._hash_buffer[self._hash.digest_size + self._buffer_idx] = byte
      self._buffer_idx += 1
    elif self._buffer_idx < self.BUFFER_SIZE:
      self._buffer[self._buffer_idx] = byte
      self._hash.update(bytes((byte,)))
      self._buffer_idx += 1
  
  def incoming_bytes(self, b):
    for byte in b: self._incoming_byte(byte)
  
  def outgoing_bytes(self, b):
    raise NotImplementedError('subclass must override "outgoing_bytes" method')
  
  def _check_hash(self):
    return True if self._hash.digest() == self._hash_buffer else False
  
  def _complete_short(self):
    if not self._check_hash():
      logging.debug('%s failed to parse short-header AppleTalk datagram from point-to-point data: bad hash', str(self))
      return
    if self._buffer_idx < 2:
      logging.debug('%s failed to parse short-header AppleTalk datagram from point-to-point data: too short', str(self))
      return
    try:
      datagram = Datagram.from_short_header_bytes(self._buffer[0], self._buffer[1], bytes(self._buffer[2:self._buffer_idx]))
    except ValueError as e:
      logging.debug('%s failed to parse short-header AppleTalk datagram from point-to-point data: %s', str(self), e.args[0])
    else:
      log_datagram_inbound(None, None, datagram, self)
      self._router.inbound(datagram, self)
  
  def _complete_long(self):
    if not self._check_hash():
      logging.debug('%s failed to parse short-header AppleTalk datagram from point-to-point data: bad hash', str(self))
      return
    if self._buffer_idx < 0:
      logging.debug('%s failed to parse long-header AppleTalk datagram from point-to-point data: too short', str(self))
      return
    try:
      datagram = Datagram.from_long_header_bytes(bytes(self._buffer[:self._buffer_idx]), verify_checksum=False)
    except ValueError as e:
      logging.debug('%s failed to parse long-header AppleTalk datagram from point-to-point data: %s', str(self), e.args[0])
    else:
      log_datagram_inbound(None, None, datagram, self)
      self._router.inbound(datagram, self)
  
  def _send_datagram(self, datagram):
    if datagram.header_type == Datagram.HEADER_TYPE_SHORT:
      b = bytes((datagram.destination_node, datagram.source_node)) + datagram.as_short_header_bytes()
    else:
      b = datagram.as_long_header_bytes()
    h = self.HASH_CLASS()
    h.update(b)
    b = h.digest() + b
    b = b.replace(bytes((self.ESC_BYTE,)), bytes((self.ESC_BYTE, self.ESC_ESC)))
    b = bytes((self.ESC_BYTE, self.ESC_START)) + b
    b += bytes((self.ESC_BYTE, self.ESC_END_SHORT if datagram.header_type == Datagram.HEADER_TYPE_SHORT else self.ESC_END_LONG))
    self.outgoing_bytes(b)
  
  def unicast(self, network, node, datagram):
    log_datagram_unicast(None, None, datagram, self)
    self._send_datagram(datagram)
  
  def broadcast(self, datagram):
    log_datagram_broadcast(datagram, self)
    self._send_datagram(datagram)
  
  def multicast(self, zone_name, datagram):
    log_datagram_multicast(zone_name, datagram, self)
    self._send_datagram(datagram)
  
  def set_network_range(self, network_min, network_max):
    pass  # point-to-point ports have no network number
  
  @staticmethod
  def multicast_address(_):
    return b''  # point-to-point ports have no multicast address
