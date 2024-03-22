'''Datagram class.'''

import dataclasses
import struct


def ddp_checksum(data):
  '''Calculate the checksum used in DDP header as well as in determining multicast addresses.'''
  retval = 0
  for byte in data:
    retval += byte
    retval = (retval & 0x7FFF) << 1 | (1 if retval & 0x8000 else 0)
  return retval or 0xFFFF  # because a zero value in the checksum field means one was not calculated


@dataclasses.dataclass
class Datagram:
  '''DDP datagram.'''
  
  MAX_DATA_LENGTH = 586
  
  hop_count: int
  destination_network: int
  source_network: int
  destination_node: int
  source_node: int
  destination_socket: int
  source_socket: int
  ddp_type: int
  data: bytes
  
  @classmethod
  def from_long_header_bytes(cls, data, verify_checksum=True):
    '''Construct a Datagram object from bytes in the long-header format and raise ValueErrors if there are issues.'''
    if len(data) < 13: raise ValueError('data too short, must be at least 13 bytes for long-header DDP datagram')
    (first, second, checksum, destination_network, source_network, destination_node, source_node, destination_socket, source_socket,
     ddp_type) = struct.unpack('>BBHHHBBBBB', data[:13])
    if first & 0xC0: raise ValueError('invalid long DDP header, top two bits of first byte must be zeroes')
    hop_count = (first & 0x3C) >> 2
    length = (first & 0x3) << 8 | second
    if length > 13 + cls.MAX_DATA_LENGTH:
      raise ValueError('invalid long DDP header, length %d is greater than %d' % (length, cls.MAX_DATA_LENGTH))
    if length != len(data):
      raise ValueError('invalid long DDP header, length field says %d but actual length is %d' % (length, len(data)))
    if checksum != 0 and verify_checksum:
      calc_checksum = ddp_checksum(data[4:])
      if calc_checksum != checksum:
        raise ValueError('invalid long DDP header, checksum is 0x%04X but should be 0x%04X' % (checksum, calc_checksum))
    return cls(hop_count=hop_count,
               destination_network=destination_network,
               source_network=source_network,
               destination_node=destination_node,
               source_node=source_node,
               destination_socket=destination_socket,
               source_socket=source_socket,
               ddp_type=ddp_type,
               data=data[13:])
  
  @classmethod
  def from_short_header_bytes(cls, destination_node, source_node, data):
    '''Construct a Datagram object from bytes in the short-header format and raise ValueErrors if there are issues.'''
    if len(data) < 5: raise ValueError('data too short, must be at least 5 bytes for short-header DDP datagram')
    first, second, destination_socket, source_socket, ddp_type = struct.unpack('>BBBBB', data[0:5])
    if first & 0xFC: raise ValueError('invalid short DDP header, top six bits of first byte must be zeroes')
    length = (first & 0x3) << 8 | second
    if length > 5 + cls.MAX_DATA_LENGTH:
      raise ValueError('invalid short DDP header, length %d is greater than %d' % (length, cls.MAX_DATA_LENGTH))
    if length != len(data):
      raise ValueError('invalid short DDP header, length field says %d but actual length is %d' % (length, len(data)))
    return cls(hop_count=0,
               destination_network=0,
               source_network=0,
               destination_node=destination_node,
               source_node=source_node,
               destination_socket=destination_socket,
               source_socket=source_socket,
               ddp_type=ddp_type,
               data=data[5:])
  
  def _check_ranges(self):
    '''Check that the Datagram's parameters are in range, raise ValueError if not.'''
    for name, min_value, max_value in (('hop count', 0, 15),
                                       ('destination network', 0, 65534),
                                       ('source network', 0, 65534),
                                       ('destination node', 0, 255),
                                       ('source node', 1, 254),
                                       ('destination socket', 0, 255),
                                       ('source socket', 0, 255),
                                       ('DDP type', 0, 255)):
      value = getattr(self, name.lower().replace(' ', '_'))
      if not min_value <= value <= max_value:
        raise ValueError('invalid %s %d, must be in range %d-%d' % (name, value, min_value, max_value))
  
  def as_long_header_bytes(self, calculate_checksum=True):
    '''Return this Datagram in long-header format as bytes and raise ValueErrors if there are issues.'''
    self._check_ranges()
    if len(self.data) > self.MAX_DATA_LENGTH:
      raise ValueError('data length %d is greater than max length %d' % (len(self.data), self.MAX_DATA_LENGTH))
    header = struct.pack('>HHBBBBB',
                         self.destination_network,
                         self.source_network,
                         self.destination_node,
                         self.source_node,
                         self.destination_socket,
                         self.source_socket,
                         self.ddp_type)
    data = header + self.data
    length = 4 + len(data)
    header = struct.pack('>BBH',
                         (self.hop_count & 0xF) << 2 | (length & 0x300) >> 8,
                         length & 0xFF,
                         ddp_checksum(data) if calculate_checksum else 0x0000)
    return header + data
  
  def as_short_header_bytes(self):
    '''Return this Datagram in short-header format as bytes and raise ValueErrors if there are issues.'''
    if self.hop_count > 0:
      raise ValueError('invalid hop count %d, short-header datagrams may not have non-zero hop count' % self.hop_count)
    self._check_ranges()
    if len(self.data) > self.MAX_DATA_LENGTH:
      raise ValueError('data length %d is greater than max length %d' % (len(self.data), self.MAX_DATA_LENGTH))
    length = 5 + len(self.data)
    header = struct.pack('>BBBBB',
                         (length & 0x300) >> 8,
                         length & 0xFF,
                         self.destination_socket,
                         self.source_socket,
                         self.ddp_type)
    return header + self.data
  
  def copy(self, **kwargs):
    '''Return a copy of this Datagram, replacing params specified by kwargs, if any.'''
    return dataclasses.replace(self, **kwargs)
  
  def hop(self):
    '''Return a copy of this Datagram with the hop count incremented by one.'''
    return self.copy(hop_count=self.hop_count + 1)
