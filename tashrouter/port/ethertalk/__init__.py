'''Superclass for EtherTalk Ports.'''

from collections import deque
import struct
from threading import Thread, Event, Lock
import time

from .. import Port
from ...datagram import Datagram, ddp_checksum
from ...router.zone_information_table import ucase


class EtherTalkPort(Port):
  '''Superclass for EtherTalk Ports.'''
  
  IEEE_802_2_SAP_OTHER = 0xAA
  IEEE_802_2_DATAGRAM_SVC_CTRL = 0x03
  IEEE_802_2_TYPE_1_HEADER = bytes((IEEE_802_2_SAP_OTHER, IEEE_802_2_SAP_OTHER, IEEE_802_2_DATAGRAM_SVC_CTRL))
  SNAP_HEADER_AARP = bytes((0x00, 0x00, 0x00, 0x80, 0xF3))
  SNAP_HEADER_APPLETALK = bytes((0x08, 0x00, 0x07, 0x80, 0x9B))
  
  AARP_ETHERNET = bytes((0x00, 0x01))
  AARP_APPLETALK = bytes((0x80, 0x9B))
  AARP_HW_ADDR_LEN = 6
  AARP_PROTOCOL_ADDR_LEN = 4
  AARP_LENGTHS = bytes((AARP_HW_ADDR_LEN, AARP_PROTOCOL_ADDR_LEN))
  AARP_HEADER = IEEE_802_2_TYPE_1_HEADER + SNAP_HEADER_AARP + AARP_ETHERNET + AARP_APPLETALK + AARP_LENGTHS
  
  AARP_REQUEST = 1
  AARP_RESPONSE = 2
  AARP_PROBE = 3
  
  AARP_PROBE_TIMEOUT = 0.2  # seconds
  AARP_PROBE_RETRIES = 10
  
  APPLETALK_HEADER = IEEE_802_2_TYPE_1_HEADER + SNAP_HEADER_APPLETALK
  
  ELAP_BROADCAST_ADDR = bytes((0x09, 0x00, 0x07, 0xFF, 0xFF, 0xFF))
  ELAP_MULTICAST_PREFIX = bytes((0x09, 0x00, 0x07, 0x00, 0x00))
  ELAP_MULTICAST_ADDR_MAX = 0xFC
  ELAP_MULTICAST_ADDRS = tuple(bytes((0x09, 0x00, 0x07, 0x00, 0x00, i)) for i in range(ELAP_MULTICAST_ADDR_MAX + 1))
  
  AMT_MAX_AGE = 10  # seconds
  AMT_AGE_INTERVAL = 1  # seconds
  HELD_DATAGRAM_MAX_AGE = 10  # seconds
  HELD_DATAGRAM_AGE_INTERVAL = 1  # seconds
  HELD_DATAGRAM_AARP_REQUEST_INTERVAL = 0.25  # seconds
  
  def __init__(self, ethernet_address, network_min=0, network_max=0, desired_network=0, desired_node=0):
    self.network_min = network_min
    self.network_max = network_max
    self.network = 0
    self.node = 0
    self.extended_network = True
    self._ethernet_address = ethernet_address
    self._desired_network = desired_network
    self._desired_node = desired_node
    self._router = None
    self._address_mapping_table = {}  # (network, node) -> (ethernet address [bytes], time.monotonic() value when last used)
    self._held_datagrams = {}  # (network, node) -> deque((Datagram, time.monotonic() value when inserted))
    self._tables_lock = Lock()
    self._age_held_datagrams_thread = None
    self._age_held_datagrams_started_event = Event()
    self._age_held_datagrams_stop_event = Event()
    self._age_held_datagrams_stopped_event = Event()
    self._send_aarp_requests_thread = None
    self._send_aarp_requests_started_event = Event()
    self._send_aarp_requests_stop_event = Event()
    self._send_aarp_requests_stopped_event = Event()
    self._age_address_mapping_table_thread = None
    self._age_address_mapping_table_started_event = Event()
    self._age_address_mapping_table_stop_event = Event()
    self._age_address_mapping_table_stopped_event = Event()
    
  def _send_datagram(self, ethernet_address, datagram):
    '''Turn a Datagram into an Ethernet frame and send it to the given address.'''
    payload = b''.join((self.APPLETALK_HEADER, datagram.as_long_header_bytes()))
    pad = b'\0' * (46 - len(payload)) if len(payload) < 46 else b''
    self.send_frame(b''.join((ethernet_address, self._ethernet_address, struct.pack('>H', len(payload)), payload, pad)))
  
  def _send_aarp_request(self, network, node):
    '''Create an AARP request for the given network and node and broadcast it to all AppleTalk nodes.'''
    payload = b''.join((self.AARP_HEADER, struct.pack('>H', self.AARP_REQUEST), self._ethernet_address,
                        struct.pack('>BHBHLBHB', 0, self.network, self.node, 0, 0, 0, network, node)))
    pad = b'\0' * (46 - len(payload)) if len(payload) < 46 else b''
    self.send_frame(b''.join((self.ELAP_BROADCAST_ADDR, self._ethernet_address, struct.pack('>H', len(payload)), payload, pad)))
  
  def _add_address_mapping(self, network, node, ethernet_address):
    '''Add an address mapping for the given network, node, and Ethernet address and release any held Datagrams waiting on it.'''
    with self._tables_lock:
      self._address_mapping_table[(network, node)] = (ethernet_address, time.monotonic())
      if (network, node) in self._held_datagrams:
        for datagram, _ in self._held_datagrams[(network, node)]: self._send_datagram(ethernet_address, datagram)
        self._held_datagrams.pop((network, node))
  
  def _send_aarp_requests_run(self):
    '''Thread for sending AARP requests for held Datagrams.'''
    self._send_aarp_requests_started_event.set()
    while not self._send_aarp_requests_stop_event.wait(timeout=self.HELD_DATAGRAM_AARP_REQUEST_INTERVAL):
      with self._tables_lock:
        for network, node in self._held_datagrams.keys(): self._send_aarp_request(network, node)
    self._send_aarp_requests_stopped_event.set()
  
  def _age_held_datagrams_run(self):
    '''Thread for aging held Datagrams.'''
    self._age_held_datagrams_started_event.set()
    while not self._age_held_datagrams_stop_event.wait(timeout=self.HELD_DATAGRAM_AGE_INTERVAL):
      with self._tables_lock:
        now = time.monotonic()
        new_held_datagrams = {}
        for network_node, datagram_hold_times in self._held_datagrams.items():
          new_datagram_hold_times = deque()
          for datagram, hold_time in datagram_hold_times:
            if now - hold_time < self.HELD_DATAGRAM_MAX_AGE: new_datagram_hold_times.append((datagram, hold_time))
          if new_datagram_hold_times:
            new_held_datagrams[network_node] = new_datagram_hold_times
        self._held_datagrams = new_held_datagrams
    self._age_held_datagrams_stopped_event.set()
  
  def _age_address_mapping_table_run(self):
    '''Thread for aging entries in the Address Mapping Table.'''
    self._age_address_mapping_table_started_event.set()
    while not self._age_address_mapping_table_stop_event.wait(timeout=self.AMT_AGE_INTERVAL):
      with self._tables_lock:
        now = time.monotonic()
        entries_to_remove = deque(network_node for network_node, address_last_used_time in self._address_mapping_table.items()
                                  if now - address_last_used_time[1] >= self.AMT_MAX_AGE)
        for entry_to_remove in entries_to_remove: self._address_mapping_table.pop(entry_to_remove)
    self._age_address_mapping_table_stopped_event.set()
  
  def _process_aarp_frame(self, frame_data):
    pass #TODO
  
  def _glean_from_aarp_frame(self, frame_data):
    pass #TODO
  
  def inbound_frame(self, frame_data):
    '''Called by subclass with inbound Ethernet frames.'''
    if frame_data[14:17] != self.IEEE_802_2_TYPE_1_HEADER: return
    length = struct.unpack('>H', frame_data[12:14])[0]
    if length > len(frame_data) + 14: return  # probably an ethertype
    if frame_data[17:22] == self.SNAP_HEADER_AARP:
      pass #TODO
    elif frame_data[17:22] == self.SNAP_HEADER_APPLETALK:
      try:
        datagram = Datagram.from_long_header_bytes(frame_data[22:14 + length])
      except ValueError:
        return
      if datagram.hop_count == 0: self._add_address_mapping(datagram.source_network, datagram.source_node, frame_data[6:12])
      if (frame_data.startswith((self._ethernet_address, self.ELAP_BROADCAST_ADDR)) or
          (frame_data.startswith(self.ELAP_MULTICAST_PREFIX) and frame_data[5] <= self.ELAP_MULTICAST_ADDR_MAX)):
        self._router.inbound(datagram)
  
  def send_frame(self, frame_data):
    '''Implemented by subclass to send Ethernet frames.'''
    raise NotImplementedError('subclass must override "send_frame" method')
  
  def start(self, router):
    '''Start this Port with the given Router.  Subclass should call this and add its own threads in its implementation.'''
    self._router = router
    self._age_held_datagrams_thread = Thread(target=self._age_held_datagrams_run)
    self._age_held_datagrams_thread.start()
    self._send_aarp_requests_thread = Thread(target=self._send_aarp_requests_run)
    self._send_aarp_requests_thread.start()
    self._age_address_mapping_table_thread = Thread(target=self._age_address_mapping_table_run)
    self._age_address_mapping_table_thread.start()
    self._age_held_datagrams_started_event.wait()
    self._send_aarp_requests_started_event.wait()
    self._age_address_mapping_table_started_event.wait()
  
  def stop(self):
    '''Stop this Port.  Subclass should call this and add its own threads in its implementation.'''
    self._age_held_datagrams_stop_event.set()
    self._send_aarp_requests_stop_event.set()
    self._age_address_mapping_table_stop_event.set()
    self._age_held_datagrams_stopped_event.wait()
    self._send_aarp_requests_stopped_event.wait()
    self._age_address_mapping_table_stopped_event.wait()
  
  def send(self, network, node, datagram):
    '''Called by Router to send a Datagram to a given network and node.'''
    with self._tables_lock:
      if (network, node) in self._address_mapping_table:
        ethernet_address, _ = self._address_mapping_table[(network, node)]
        self._send_datagram(ethernet_address, datagram)
      elif (network, node) in self._held_datagrams:
        self._held_datagrams[(network, node)].append((datagram, time.monotonic()))
      else:
        self._held_datagrams[(network, node)] = deque(((datagram, time.monotonic()),))
        self._send_aarp_request(network, node)
  
  def multicast(self, zone_name, datagram):
    '''Called by Router to make a zone-wide multicast of a Datagram.'''
    self._send_datagram(self.multicast_address(zone_name), datagram)
  
  def set_network_range(self, network_min, network_max):
    #TODO
    #self.network = ?
    self.network_min = network_min
    self.network_max = network_max
    self._router.routing_table.set_port_range(self, self.network_min, self.network_max)
  
  @classmethod
  def multicast_address(cls, zone_name):
    '''Return the ELAP multicast address for the named zone.'''
    return cls.ELAP_MULTICAST_ADDRS[ddp_checksum(ucase(zone_name)) % len(cls.ELAP_MULTICAST_ADDRS)]
