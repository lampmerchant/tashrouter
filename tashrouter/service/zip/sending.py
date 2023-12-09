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
        #TODO make this more efficient - combine together queries with the same destination
        if next(router.zone_information_table.zones_in_network_range(entry.network_min, entry.network_max), None): continue
        if entry.distance == 0:
          entry.port.send(0x0000, 0xFF, Datagram(hop_count=0,
                                                 destination_network=0x0000,
                                                 source_network=entry.port.network,
                                                 destination_node=0xFF,
                                                 source_node=entry.port.node,
                                                 destination_socket=self.ZIP_SAS,
                                                 source_socket=self.ZIP_SAS,
                                                 ddp_type=self.ZIP_DDP_TYPE,
                                                 data=struct.pack('>BBH', self.ZIP_FUNC_QUERY, 1, entry.network_min)))
        else:
          entry.port.send(entry.next_network, entry.next_node, Datagram(hop_count=0,
                                                                        destination_network=entry.next_network,
                                                                        source_network=entry.port.network,
                                                                        destination_node=entry.next_node,
                                                                        source_node=entry.port.node,
                                                                        destination_socket=self.ZIP_SAS,
                                                                        source_socket=self.ZIP_SAS,
                                                                        ddp_type=self.ZIP_DDP_TYPE,
                                                                        data=struct.pack('>BBH', self.ZIP_FUNC_QUERY, 1, 
                                                                                         entry.network_min)))
    self.stopped_event.set()
  
  def inbound(self, datagram, rx_port):
    pass
