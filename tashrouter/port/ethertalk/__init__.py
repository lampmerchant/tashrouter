'''Superclass for EtherTalk Ports.'''

from collections import deque
import logging
import random
import struct
from threading import Thread, Event, Lock
import time

from .. import Port
from ...datagram import Datagram, ddp_checksum
from ...netlog import log_datagram_inbound, log_datagram_unicast, log_datagram_broadcast, log_datagram_multicast
from ...netlog import log_ethernet_frame_inbound, log_ethernet_frame_outbound
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
  
  def __init__(self, hw_addr, seed_network_min=0, seed_network_max=0, seed_zone_names=(), desired_network=0, desired_node=0,
               verify_checksums=True, calculate_checksums=True):
    if seed_network_min and not seed_network_max or seed_network_max and not seed_network_min:
      raise ValueError('seed_network_min and seed_network_max must be provided or omitted together')
    if seed_network_min and not seed_zone_names or seed_zone_names and not seed_network_min:
      raise ValueError('seed_network_min/max and seed_zone_names must be provided or omitted together')
    self.network_min = seed_network_min
    self.network_max = seed_network_max
    self.network = 0
    self.node = 0
    self.extended_network = True
    self._hw_addr = hw_addr
    self._seed_zone_names = seed_zone_names
    self._desired_network = 0
    self._desired_node = 0
    if self.network_min:
      self._desired_network_list = [desired_network] if self.network_min <= desired_network <= self.network_max else []
      self._desired_node_list = [desired_node] if 1 <= desired_node <= 0xFD else []
      self._reroll_desired_network_and_node()
    else:
      self._desired_network_list = []
      self._desired_node_list = []
    self._verify_checksums = verify_checksums
    self._calculate_checksums = calculate_checksums
    self._aarp_probe_attempts = 0
    self._aarp_probe_lock = Lock()
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
    self._acquire_network_and_node_thread = None
    self._acquire_network_and_node_started_event = Event()
    self._acquire_network_and_node_stop_event = Event()
    self._acquire_network_and_node_stopped_event = Event()
  
  def _reroll_desired_network_and_node(self):
    '''Reroll the network and node number.'''
    if not self._desired_node_list:
      if not self._desired_network_list:
        self._desired_network_list = list(range(self.network_min, self.network_max + 1))
        random.shuffle(self._desired_network_list)
      self._desired_network = self._desired_network_list.pop()
      self._desired_node_list = list(range(1, 0xFD + 1))
      random.shuffle(self._desired_node_list)
    self._desired_node = self._desired_node_list.pop()
    self._aarp_probe_attempts = 0
  
  def _send_frame(self, hw_addr, payload):
    '''Send a payload to an Ethernet address, padding if necessary.'''
    pad = b'\0' * (46 - len(payload)) if len(payload) < 46 else b''
    frame_data = b''.join((hw_addr, self._hw_addr, struct.pack('>H', len(payload)), payload, pad))
    log_ethernet_frame_outbound(frame_data, self)
    self.send_frame(frame_data)
  
  def _send_datagram(self, hw_addr, datagram):
    '''Turn a Datagram into an Ethernet frame and send it to the given address.'''
    self._send_frame(hw_addr, b''.join((self.APPLETALK_HEADER,
                                        datagram.as_long_header_bytes(calculate_checksum=self._calculate_checksums))))
  
  def _send_aarp_request(self, network, node):
    '''Create an AARP request for the given network and node and broadcast it to all AppleTalk nodes.'''
    if not self.network or not self.node or node == 0xFF: return
    self._send_frame(self.ELAP_BROADCAST_ADDR, b''.join((self.AARP_HEADER, struct.pack('>H', self.AARP_REQUEST),
                                                         self._hw_addr,
                                                         struct.pack('>BHBHLBHB',
                                                                     0, self.network, self.node,
                                                                     0, 0,
                                                                     0, network, node))))
  
  def _send_aarp_response(self, destination_hw_addr, destination_network, destination_node):
    '''Create an AARP response containing our address and send it to the given destination.'''
    if not self.network or not self.node: return
    self._send_frame(destination_hw_addr, b''.join((self.AARP_HEADER, struct.pack('>H', self.AARP_RESPONSE),
                                                    self._hw_addr,
                                                    struct.pack('>BHB', 0, self.network, self.node),
                                                    destination_hw_addr,
                                                    struct.pack('>BHB', 0, destination_network, destination_node))))
  
  def _send_aarp_probe(self, network, node):
    '''Create an AARP probe for the given network and node and broadcast it to all AppleTalk nodes.'''
    self._send_frame(self.ELAP_BROADCAST_ADDR, b''.join((self.AARP_HEADER, struct.pack('>H', self.AARP_PROBE),
                                                         self._hw_addr,
                                                         struct.pack('>BHBHLBHB',
                                                                     0, network, node,
                                                                     0, 0,
                                                                     0, network, node))))
  
  def _add_address_mapping(self, network, node, mapped_hw_addr):
    '''Add an address mapping for the given network, node, and Ethernet address and release any held Datagrams waiting on it.'''
    datagrams_to_send = deque()
    with self._tables_lock:
      self._address_mapping_table[(network, node)] = (mapped_hw_addr, time.monotonic())
      if (network, node) in self._held_datagrams:
        for datagram, _ in self._held_datagrams[(network, node)]: datagrams_to_send.append((mapped_hw_addr, datagram))
        self._held_datagrams.pop((network, node))
    for hw_addr, datagram in datagrams_to_send: self._send_datagram(hw_addr, datagram)
  
  def _send_aarp_requests_run(self):
    '''Thread for sending AARP requests for held Datagrams.'''
    self._send_aarp_requests_started_event.set()
    while not self._send_aarp_requests_stop_event.wait(timeout=self.HELD_DATAGRAM_AARP_REQUEST_INTERVAL):
      with self._tables_lock: aarp_requests = deque(self._held_datagrams.keys())
      for network, node in aarp_requests: self._send_aarp_request(network, node)
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
  
  def _acquire_network_and_node_run(self):
    '''Thread for acquiring a network and node number.'''
    if self.network_min and self.network_max:
      self._set_network_range(self.network_min, self.network_max)
      for zone_name in self._seed_zone_names:
        self._router.zone_information_table.add_networks_to_zone(zone_name, self.network_min, self.network_max)
    self._acquire_network_and_node_started_event.set()
    while not self._acquire_network_and_node_stop_event.wait(timeout=self.AARP_PROBE_TIMEOUT):
      send_aarp_probe = None
      with self._aarp_probe_lock:
        if self._aarp_probe_attempts >= self.AARP_PROBE_RETRIES:
          logging.info('%s claiming address %d.%d', str(self), self._desired_network, self._desired_node)
          self.network = self._desired_network
          self.node = self._desired_node
          break
        if self._desired_network and self._desired_node:
          send_aarp_probe = (self._desired_network, self._desired_node)
          self._aarp_probe_attempts += 1
      if send_aarp_probe:
        desired_network, desired_node = send_aarp_probe
        self._send_aarp_probe(desired_network, desired_node)
    self._acquire_network_and_node_stopped_event.set()
  
  def _process_aarp_frame(self, func, source_hw_addr, source_network, source_node):
    '''Process and act on an inbound AARP frame.'''
    if func in (self.AARP_REQUEST, self.AARP_PROBE):
      self._send_aarp_response(source_hw_addr, source_network, source_node)
    elif func == self.AARP_RESPONSE:
      self._add_address_mapping(source_network, source_node, source_hw_addr)
      with self._aarp_probe_lock:
        if self.network == self.node == 0 and source_network == self._desired_network and source_node == self._desired_node:
          self._reroll_desired_network_and_node()
  
  def inbound_frame(self, frame_data):
    '''Called by subclass with inbound Ethernet frames.'''
    
    if frame_data[14:17] != self.IEEE_802_2_TYPE_1_HEADER: return
    length = struct.unpack('>H', frame_data[12:14])[0]
    if length > len(frame_data) + 14: return  # probably an ethertype
    
    if frame_data[17:22] == self.SNAP_HEADER_AARP and length == 36:
      
      if frame_data[22:28] != b''.join((self.AARP_ETHERNET, self.AARP_APPLETALK, self.AARP_LENGTHS)): return
      
      log_ethernet_frame_inbound(frame_data, self)
      
      func, source_hw_addr, _, source_network, source_node = struct.unpack('>H6sBHB', frame_data[28:40])
      
      if frame_data.startswith(self._hw_addr) or (func == self.AARP_REQUEST and frame_data.startswith(self.ELAP_BROADCAST_ADDR)):
        self._process_aarp_frame(func, source_hw_addr, source_network, source_node)
      elif func == self.AARP_RESPONSE:
        self._add_address_mapping(source_network, source_node, source_hw_addr)
      
    elif frame_data[17:22] == self.SNAP_HEADER_APPLETALK:
      
      log_ethernet_frame_inbound(frame_data, self)
      
      try:
        datagram = Datagram.from_long_header_bytes(frame_data[22:14 + length], verify_checksum=self._verify_checksums)
      except ValueError as e:
        logging.debug('%s failed to parse AppleTalk datagram from EtherTalk frame: %s', str(self), e.args[0])
      else:
        if datagram.hop_count == 0: self._add_address_mapping(datagram.source_network, datagram.source_node, frame_data[6:12])
        if (frame_data.startswith((self._hw_addr, self.ELAP_BROADCAST_ADDR)) or
            (frame_data.startswith(self.ELAP_MULTICAST_PREFIX) and frame_data[5] <= self.ELAP_MULTICAST_ADDR_MAX)):
          log_datagram_inbound(self.network, self.node, datagram, self)
          self._router.inbound(datagram, self)
  
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
    self._acquire_network_and_node_thread = Thread(target=self._acquire_network_and_node_run)
    self._acquire_network_and_node_thread.start()
    self._age_held_datagrams_started_event.wait()
    self._send_aarp_requests_started_event.wait()
    self._age_address_mapping_table_started_event.wait()
    self._acquire_network_and_node_started_event.wait()
  
  def stop(self):
    '''Stop this Port.  Subclass should call this and add its own threads in its implementation.'''
    self._age_held_datagrams_stop_event.set()
    self._send_aarp_requests_stop_event.set()
    self._age_address_mapping_table_stop_event.set()
    self._acquire_network_and_node_stop_event.set()
    self._age_held_datagrams_stopped_event.wait()
    self._send_aarp_requests_stopped_event.wait()
    self._age_address_mapping_table_stopped_event.wait()
    self._acquire_network_and_node_stopped_event.wait()
  
  def unicast(self, network, node, datagram):
    log_datagram_unicast(network, node, datagram, self)
    send_datagram = None
    send_aarp_request = None
    with self._tables_lock:
      if (network, node) in self._address_mapping_table:
        hw_addr, _ = self._address_mapping_table[(network, node)]
        send_datagram = (hw_addr, datagram)
      elif (network, node) in self._held_datagrams:
        self._held_datagrams[(network, node)].append((datagram, time.monotonic()))
      else:
        self._held_datagrams[(network, node)] = deque(((datagram, time.monotonic()),))
        send_aarp_request = (network, node)
    if send_datagram:
      hw_addr, datagram = send_datagram
      self._send_datagram(hw_addr, datagram)
    if send_aarp_request:
      network, node = send_aarp_request
      self._send_aarp_request(network, node)
  
  def broadcast(self, datagram):
    log_datagram_broadcast(datagram, self)
    if (datagram.destination_network, datagram.destination_node) != (0x0000, 0xFF):
      datagram = datagram.copy(destination_network=0x0000, destination_node=0xFF)
    self._send_datagram(self.ELAP_BROADCAST_ADDR, datagram)
  
  def multicast(self, zone_name, datagram):
    log_datagram_multicast(zone_name, datagram, self)
    self._send_datagram(self.multicast_address(zone_name), datagram)
  
  def _set_network_range(self, network_min, network_max):
    logging.info('%s assigned network number range %d-%d', str(self), network_min, network_max)
    self.network_min = network_min
    self.network_max = network_max
    self._router.routing_table.set_port_range(self, self.network_min, self.network_max)
    self.network = 0
    self.node = 0
    with self._aarp_probe_lock:
      self._desired_network_list = []
      self._desired_node_list = []
      self._reroll_desired_network_and_node()
  
  def set_network_range(self, network_min, network_max):
    '''Called by RTMP responding service when we don't have a network range but an RTMP datagram tells us what ours is.'''
    if self.network_min or self.network_max:
      raise ValueError('%s assigned network number range %d-%d but already has %d-%d' % (str(self), network_min, network_max,
                                                                                         self.network_min, self.network_max))
    self._set_network_range(network_min, network_max)
  
  @classmethod
  def multicast_address(cls, zone_name):
    '''Return the ELAP multicast address for the named zone.'''
    return cls.ELAP_MULTICAST_ADDRS[ddp_checksum(ucase(zone_name)) % len(cls.ELAP_MULTICAST_ADDRS)]
