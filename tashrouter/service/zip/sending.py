'''ZIP (Zone Information Protocol) sending service.'''

from collections import deque
from itertools import chain
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
      for entry in router.routing_table:
        query_data_blocks = deque()
        query_data_block = deque()
        for network in chain(router.zone_information_table.networks_not_known(range(entry.network_min, entry.network_max + 1)),
                             (None,)):
          if network is None or len(query_data_block) == (Datagram.MAX_DATA_LENGTH - 2) // 2:
            if query_data_block:
              query_data_block.appendleft(struct.pack('>BB', self.ZIP_FUNC_QUERY, len(query_data_block)))
              query_data_blocks.append(b''.join(query_data_block))
            if network is not None: query_data_block = deque((struct.pack('>H', network),))
          else:
            query_data_block.append(struct.pack('>H', network))
        for query_data_block in query_data_blocks:
          if entry.distance == 0:
            entry.port.send(entry.port.network, 0xFF, Datagram(hop_count=0,
                                                               destination_network=entry.port.network,
                                                               source_network=entry.port.network,
                                                               destination_node=0xFF,
                                                               source_node=entry.port.node,
                                                               destination_socket=self.ZIP_SAS,
                                                               source_socket=self.ZIP_SAS,
                                                               ddp_type=self.ZIP_DDP_TYPE,
                                                               data=query_data_block))
          else:
            entry.port.send(entry.next_network, entry.next_node, Datagram(hop_count=0,
                                                                          destination_network=entry.next_network,
                                                                          source_network=entry.port.network,
                                                                          destination_node=entry.next_node,
                                                                          source_node=entry.port.node,
                                                                          destination_socket=self.ZIP_SAS,
                                                                          source_socket=self.ZIP_SAS,
                                                                          ddp_type=self.ZIP_DDP_TYPE,
                                                                          data=query_data_block))
    self.stopped_event.set()
  
  def inbound(self, datagram, rx_port):
    pass
