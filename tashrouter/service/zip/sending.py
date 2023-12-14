'''ZIP (Zone Information Protocol) sending service.'''

from collections import deque
from itertools import chain
import logging
import struct
from threading import Thread, Event

from . import ZipService
from .. import Service
from ...datagram import Datagram


class ZipSendingService(Service, ZipService):
  '''A Service which sends ZIP queries to fill out its router's Zone Information Table.'''
  
  DEFAULT_TIMEOUT = 10  # seconds
  
  def __init__(self, timeout=DEFAULT_TIMEOUT):
    self.timeout = timeout
    self.thread = None
    self.started_event = Event()
    self.stop_requested_event = Event()
    self.stopped_event = Event()
  
  def start(self, router):
    self.thread = Thread(target=self._run, args=(router,))
    self.thread.start()
    self.started_event.wait()
  
  def stop(self):
    self.stop_requested_event.set()
    self.stopped_event.wait()
  
  def _run(self, router):
    
    self.started_event.set()
    
    while True:
      
      if self.stop_requested_event.wait(timeout=self.timeout): break
      
      queries = {}  # (port, network, node) -> network_mins
      for entry in router.routing_table:
        try:
          if next(router.zone_information_table.zones_in_network_range(entry.network_min, entry.network_max), None): continue
        except ValueError as e:
          logging.warning('%s apparent disjoin between routing table and zone information table: %s', router, e.args[0])
          continue
        if entry.distance == 0:
          key = (entry.port, 0x0000, 0xFF)
        else:
          key = (entry.port, entry.next_network, entry.next_node)
        if key not in queries: queries[key] = deque()
        queries[key].append(entry.network_min)
      
      for port_network_node, network_mins in queries.items():
        port, network, node = port_network_node
        if 0 in (port.node, port.network): continue
        datagram_data = deque()
        for network_min in chain(network_mins, (None,)):
          if network_min is None or len(datagram_data) * 2 + 4 > Datagram.MAX_DATA_LENGTH:
            datagram_data.appendleft(struct.pack('>BB', self.ZIP_FUNC_QUERY, len(datagram_data)))
            port.send(network, node, Datagram(hop_count=0,
                                              destination_network=network,
                                              source_network=port.network,
                                              destination_node=node,
                                              source_node=port.node,
                                              destination_socket=self.ZIP_SAS,
                                              source_socket=self.ZIP_SAS,
                                              ddp_type=self.ZIP_DDP_TYPE,
                                              data=b''.join(datagram_data)))
            if network_min is not None: datagram_data = deque((struct.pack('>H', network_min),))
          else:
            datagram_data.append(struct.pack('>H', network_min))
      
    self.stopped_event.set()
  
  def inbound(self, datagram, rx_port):
    pass
