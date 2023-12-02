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
  def from_long_header_bytes(cls, packet_bytes):
    '''Construct a Datagram from the bytes of a long-header packet and raise ValueErrors if there are issues.'''
    if len(packet_bytes) < 13: raise ValueError('packet too short, must be at least 13 bytes for long-header DDP datagram')
    (first, second, checksum, destination_network, source_network, destination_node, source_node, destination_socket, source_socket,
     ddp_type) = struct.unpack('>BBHHHBBBBB', packet_bytes[:13])
    if first & 0xC0: raise ValueError('invalid long-header packet, top two bits of first byte must be zeroes')
    hop_count = (first & 0x3C) >> 2
    length = (first & 0x3) << 8 | second
    if length > 13 + cls.MAX_DATA_LENGTH:
      raise ValueError('invalid long-header packet, length %d is greater than %d' % (length, cls.MAX_DATA_LENGTH))
    if length != len(packet_bytes):
      raise ValueError('invalid long-header packet, length field says %d but actual length is %d' % (length, len(packet_bytes)))
    if checksum != 0:
      calc_checksum = ddp_checksum(packet_bytes[4:])
      if calc_checksum != checksum:
        raise ValueError('invalid long-header packet, checksum is 0x%04X but should be 0x%04X' % (checksum, calc_checksum))
    return cls(hop_count=hop_count,
               destination_network=destination_network,
               source_network=source_network,
               destination_node=destination_node,
               source_node=source_node,
               destination_socket=destination_socket,
               source_socket=source_socket,
               ddp_type=ddp_type,
               data=packet_bytes[13:])
  
  @classmethod
  def from_short_header_bytes(cls, destination_node, source_node, packet_bytes):
    '''Construct a Datagram from the bytes of a short-header packet and raise ValueErrors if there are issues.'''
    if len(packet_bytes) < 5: raise ValueError('packet too short, must be at least 5 bytes for short-header DDP datagram')
    first, second, destination_socket, source_socket, ddp_type = struct.unpack('>BBBBB', packet_bytes[0:5])
    if first & 0xFC: raise ValueError('invalid short-header packet, top six bits of first byte must be zeroes')
    length = (first & 0x3) << 8 | second
    if length > 5 + cls.MAX_DATA_LENGTH:
      raise ValueError('invalid short-header packet, length %d is greater than %d' % (length, cls.MAX_DATA_LENGTH))
    if length != len(packet_bytes):
      raise ValueError('invalid short-header packet, length field says %d but actual length is %d' % (length, len(packet_bytes)))
    return cls(hop_count=0,
               destination_network=0,
               source_network=0,
               destination_node=destination_node,
               source_node=source_node,
               destination_socket=destination_socket,
               source_socket=source_socket,
               ddp_type=ddp_type,
               data=packet_bytes[5:])
  
  @classmethod
  def from_llap_packet_bytes(cls, packet_bytes):
    '''Construct a Datagram from the bytes of a packet from an LLAP network and raise ValueErrors if there are issues.
    
    Note that a "packet" from an LLAP network includes the destination, source, and type bytes but not the FCS/CRC bytes.
    '''
    if len(packet_bytes) < 8: raise ValueError('LLAP packet too short, must be at least 8 bytes for short header DDP datagram')
    destination_node, source_node, llap_type = struct.unpack('>BBB', packet_bytes[0:3])
    if llap_type == 1:  # short header
      return cls.from_short_header_bytes(destination_node, source_node, packet_bytes[3:])
    elif llap_type == 2:  # long header
      return cls.from_long_header_bytes(packet_bytes[3:])
    else:
      raise ValueError('invalid LLAP type for DDP datagram, must be 1 or 2')
  
  def _check_ranges(self):
    '''Check that the packet's parameters are in range, raise ValueError if not.'''
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
  
  def as_long_header_bytes(self):
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
    checksum = 0
    for byte in data:
      checksum += byte
      checksum = (checksum & 0x7FFF) << 1 | (1 if checksum & 0x8000 else 0)
    checksum = checksum or 0xFFFF  # because a zero value in the checksum field means one was not calculated
    header = struct.pack('>BBH',
                         (self.hop_count & 0xF) << 2 | (length & 0x300) >> 8,
                         length & 0xFF,
                         checksum)
    return header + data
  
  def as_short_header_bytes(self):
    '''Return this Datagram in short-header format as bytes and raise ValueErrors if there are issues.'''
    if self.hop_count > 0:
      raise ValueError('invalid hop count %d, short-header packets may not have non-zero hop count' % self.hop_count)
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
