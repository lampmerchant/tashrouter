'''RTMP service superclass.'''

from collections import deque
from itertools import chain
import struct

from ...datagram import Datagram


class RtmpService:
  '''A class that contains constants and common functions used by RTMP services.'''
  
  RTMP_SAS = 1
  RTMP_DDP_TYPE_DATA = 1
  RTMP_DDP_TYPE_REQUEST = 5
  RTMP_VERSION = 0x82
  RTMP_FUNC_REQUEST = 1
  RTMP_FUNC_RDR_SPLIT_HORIZON = 2
  RTMP_FUNC_RDR_NO_SPLIT_HORIZON = 3
  
  NOTIFY_NEIGHBOR = 31
  
  def make_routing_table_datagram_data(self, router, port, split_horizon=True):
    '''Build Datagram data for the given Router's RoutingTable.'''
    
    if 0 in (port.network_min, port.network_max): return

    binary_tuples = deque()
    this_net = None
    for entry, is_bad in router.routing_table.entries():
      if entry.port is port and split_horizon: continue  # split horizon
      distance = self.NOTIFY_NEIGHBOR if is_bad else entry.distance
      if not entry.port.extended_network:
        binary_tuple = struct.pack('>HB', entry.network_min, distance & 0x1F)
      else:
        binary_tuple = struct.pack('>HBHB', entry.network_min, (distance & 0x1F) | 0x80, entry.network_max, self.RTMP_VERSION)
      if port.extended_network and port.network_min == entry.network_min and port.network_max == entry.network_max:
        this_net = binary_tuple
      else:
        binary_tuples.append(binary_tuple)
    if port.extended_network and not this_net: raise ValueError("port's network range was not found in routing table")

    if port.extended_network:
      rtmp_datagram_header = struct.pack('>HBB', port.network, 8, port.node) + this_net
    else:
      rtmp_datagram_header = struct.pack('>HBBHB', port.network, 8, port.node, 0, self.RTMP_VERSION)

    next_datagram_data = deque((rtmp_datagram_header,))
    next_datagram_data_length = len(rtmp_datagram_header)
    for binary_tuple in chain(binary_tuples, (None,)):
      if binary_tuple is None or next_datagram_data_length + len(binary_tuple) > Datagram.MAX_DATA_LENGTH:
        yield b''.join(next_datagram_data)
        if binary_tuple is not None:
          next_datagram_data = deque((rtmp_datagram_header, binary_tuple))
          next_datagram_data_length = len(rtmp_datagram_header) + len(binary_tuple)
      else:
        next_datagram_data.append(binary_tuple)
        next_datagram_data_length += len(binary_tuple)

