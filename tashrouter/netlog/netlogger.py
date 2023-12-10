'''Facilities for logging of network traffic for debug and test purposes.'''

import struct


def datagram_header(datagram):
  '''Return a string that contains a datagram's header information.'''
  return '%2d %d.%-3d %d.%-3d %3d %3d %d' % (datagram.hop_count,
                                             datagram.destination_network,
                                             datagram.destination_node,
                                             datagram.source_network,
                                             datagram.source_node,
                                             datagram.destination_socket,
                                             datagram.source_socket,
                                             datagram.ddp_type)


def ethernet_frame_header(frame_data):
  '''Return a string that contains an ethernet frame's header information.'''
  if len(frame_data) < 12: return ''
  return ' '.join((''.join(('%02X' % i) for i in frame_data[0:6]), ''.join(('%02X' % i) for i in frame_data[6:12])))


def localtalk_frame_header(frame_data):
  '''Return a string that contains an ethernet frame's header information.'''
  if len(frame_data) < 3: return ''
  return '%3d %3d  type %02X' % struct.unpack('>BBB', frame_data[0:3])


class NetLogger:
  '''Class for logging of network traffic for debug and test purposes.'''
  
  def __init__(self):
    self._logging_on = False
    self._log_str_func = lambda msg: None
    self._direction_width = 0
    self._port_width = 0
    self._header_width = 0
  
  def _log_str(self, direction_str, port_str, header_str, data):
    self._direction_width = max(self._direction_width, len(direction_str))
    self._port_width = max(self._port_width, len(port_str))
    self._header_width = max(self._header_width, len(header_str))
    self._log_str_func(' '.join((direction_str.ljust(self._direction_width),
                                 port_str.ljust(self._port_width),
                                 header_str.ljust(self._header_width),
                                 str(data))))
  
  def log_datagram_inbound(self, network, node, datagram, port):
    if not self._logging_on: return
    self._log_str('in to %d.%d' % (network, node), port.short_str(), datagram_header(datagram), datagram.data)
  
  def log_datagram_outbound(self, network, node, datagram, port):
    if not self._logging_on: return
    self._log_str('out to %d.%d' % (network, node), port.short_str(), datagram_header(datagram), datagram.data)
  
  def log_datagram_multicast(self, zone_name, datagram, port):
    if not self._logging_on: return
    self._log_str('out to %s' % zone_name, port.short_str(), datagram_header(datagram), datagram.data)
  
  def log_ethernet_frame_inbound(self, frame_data, port):
    if not self._logging_on: return
    if len(frame_data) < 14: return
    length = struct.unpack('>H', frame_data[12:14])[0]
    self._log_str('frame in', port.short_str(), ethernet_frame_header(frame_data), frame_data[14:14 + length])
  
  def log_ethernet_frame_outbound(self, frame_data, port):
    if not self._logging_on: return
    if len(frame_data) < 14: return
    length = struct.unpack('>H', frame_data[12:14])[0]
    self._log_str('frame out', port.short_str(), ethernet_frame_header(frame_data), frame_data[14:14 + length])
  
  def log_localtalk_frame_inbound(self, frame_data, port):
    if not self._logging_on: return
    self._log_str('frame in', port.short_str(), localtalk_frame_header(frame_data), frame_data[3:])
  
  def log_localtalk_frame_outbound(self, frame_data, port):
    if not self._logging_on: return
    self._log_str('frame out', port.short_str(), localtalk_frame_header(frame_data), frame_data[3:])
  
  def set_log_str_func(self, func):
    self._logging_on = True
    self._log_str_func = func
