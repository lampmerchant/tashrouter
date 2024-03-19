'''Superclass for LocalTalk Ports.'''

import logging
import random
import struct
from threading import Thread, Event, Lock

from .. import Port
from ...datagram import Datagram
from ...netlog import log_datagram_inbound, log_datagram_unicast, log_datagram_broadcast, log_datagram_multicast


class FcsCalculator:
  '''Utility class to calculate the FCS (frame check sequence) of an LLAP frame.'''
  
  LLAP_FCS_LUT = (
    0x0000, 0x1189, 0x2312, 0x329B, 0x4624, 0x57AD, 0x6536, 0x74BF, 0x8C48, 0x9DC1, 0xAF5A, 0xBED3, 0xCA6C, 0xDBE5, 0xE97E, 0xF8F7,
    0x1081, 0x0108, 0x3393, 0x221A, 0x56A5, 0x472C, 0x75B7, 0x643E, 0x9CC9, 0x8D40, 0xBFDB, 0xAE52, 0xDAED, 0xCB64, 0xF9FF, 0xE876,
    0x2102, 0x308B, 0x0210, 0x1399, 0x6726, 0x76AF, 0x4434, 0x55BD, 0xAD4A, 0xBCC3, 0x8E58, 0x9FD1, 0xEB6E, 0xFAE7, 0xC87C, 0xD9F5,
    0x3183, 0x200A, 0x1291, 0x0318, 0x77A7, 0x662E, 0x54B5, 0x453C, 0xBDCB, 0xAC42, 0x9ED9, 0x8F50, 0xFBEF, 0xEA66, 0xD8FD, 0xC974,
    0x4204, 0x538D, 0x6116, 0x709F, 0x0420, 0x15A9, 0x2732, 0x36BB, 0xCE4C, 0xDFC5, 0xED5E, 0xFCD7, 0x8868, 0x99E1, 0xAB7A, 0xBAF3,
    0x5285, 0x430C, 0x7197, 0x601E, 0x14A1, 0x0528, 0x37B3, 0x263A, 0xDECD, 0xCF44, 0xFDDF, 0xEC56, 0x98E9, 0x8960, 0xBBFB, 0xAA72,
    0x6306, 0x728F, 0x4014, 0x519D, 0x2522, 0x34AB, 0x0630, 0x17B9, 0xEF4E, 0xFEC7, 0xCC5C, 0xDDD5, 0xA96A, 0xB8E3, 0x8A78, 0x9BF1,
    0x7387, 0x620E, 0x5095, 0x411C, 0x35A3, 0x242A, 0x16B1, 0x0738, 0xFFCF, 0xEE46, 0xDCDD, 0xCD54, 0xB9EB, 0xA862, 0x9AF9, 0x8B70,
    0x8408, 0x9581, 0xA71A, 0xB693, 0xC22C, 0xD3A5, 0xE13E, 0xF0B7, 0x0840, 0x19C9, 0x2B52, 0x3ADB, 0x4E64, 0x5FED, 0x6D76, 0x7CFF,
    0x9489, 0x8500, 0xB79B, 0xA612, 0xD2AD, 0xC324, 0xF1BF, 0xE036, 0x18C1, 0x0948, 0x3BD3, 0x2A5A, 0x5EE5, 0x4F6C, 0x7DF7, 0x6C7E,
    0xA50A, 0xB483, 0x8618, 0x9791, 0xE32E, 0xF2A7, 0xC03C, 0xD1B5, 0x2942, 0x38CB, 0x0A50, 0x1BD9, 0x6F66, 0x7EEF, 0x4C74, 0x5DFD,
    0xB58B, 0xA402, 0x9699, 0x8710, 0xF3AF, 0xE226, 0xD0BD, 0xC134, 0x39C3, 0x284A, 0x1AD1, 0x0B58, 0x7FE7, 0x6E6E, 0x5CF5, 0x4D7C,
    0xC60C, 0xD785, 0xE51E, 0xF497, 0x8028, 0x91A1, 0xA33A, 0xB2B3, 0x4A44, 0x5BCD, 0x6956, 0x78DF, 0x0C60, 0x1DE9, 0x2F72, 0x3EFB,
    0xD68D, 0xC704, 0xF59F, 0xE416, 0x90A9, 0x8120, 0xB3BB, 0xA232, 0x5AC5, 0x4B4C, 0x79D7, 0x685E, 0x1CE1, 0x0D68, 0x3FF3, 0x2E7A,
    0xE70E, 0xF687, 0xC41C, 0xD595, 0xA12A, 0xB0A3, 0x8238, 0x93B1, 0x6B46, 0x7ACF, 0x4854, 0x59DD, 0x2D62, 0x3CEB, 0x0E70, 0x1FF9,
    0xF78F, 0xE606, 0xD49D, 0xC514, 0xB1AB, 0xA022, 0x92B9, 0x8330, 0x7BC7, 0x6A4E, 0x58D5, 0x495C, 0x3DE3, 0x2C6A, 0x1EF1, 0x0F78,
  )
  
  def __init__(self):
    self.reg = 0
    self.reset()
  
  def reset(self):
    '''Reset the FCS calculator as though no data had been fed into it.'''
    self.reg = 0xFFFF
  
  def feed_byte(self, byte):
    '''Feed a single byte (an integer between 0 and 255) into the FCS calculator.'''
    index = (self.reg & 0xFF) ^ byte
    self.reg = self.LLAP_FCS_LUT[index] ^ (self.reg >> 8)
  
  def feed(self, data):
    '''Feed a bytes-like object into the FCS calculator.'''
    for byte in data: self.feed_byte(byte)
  
  def byte1(self):
    '''Returns the first byte of the FCS.'''
    return (self.reg & 0xFF) ^ 0xFF
  
  def byte2(self):
    '''Returns the second byte of the FCS.'''
    return (self.reg >> 8) ^ 0xFF
  
  def is_okay(self):
    '''If the FCS has been fed into the calculator and is correct, this will return True.'''
    return True if self.reg == 61624 else False  # this is the binary constant on B-22 of Inside Appletalk, but backwards


class LocalTalkPort(Port):
  '''Superclass for LocalTalk Ports.'''
  
  ENQ_INTERVAL = 0.25  # seconds
  ENQ_ATTEMPTS = 8
  
  LLAP_APPLETALK_SHORT_HEADER = 0x01
  LLAP_APPLETALK_LONG_HEADER = 0x02
  LLAP_ENQ = 0x81
  LLAP_ACK = 0x82
  
  def __init__(self, seed_network=0, seed_zone_name=None, respond_to_enq=True, desired_node=0xFE):
    if seed_network and not seed_zone_name or seed_zone_name and not seed_network:
      raise ValueError('seed_network and seed_zone_name must be provided or omitted together')
    self.network = self.network_min = self.network_max = seed_network
    self.node = 0
    self.extended_network = False
    self._router = None
    self._seed_zone_name = seed_zone_name
    self._respond_to_enq = respond_to_enq
    self._desired_node = desired_node
    self._desired_node_list = list(i for i in range(1, 0xFE + 1) if i != self._desired_node)
    random.shuffle(self._desired_node_list)
    self._desired_node_attempts = 0
    self._node_thread = None
    self._node_lock = Lock()
    self._node_started_event = Event()
    self._node_stop_event = Event()
    self._node_stopped_event = Event()
  
  def start(self, router):
    self._router = router
    self._node_thread = Thread(target=self._node_run)
    self._node_thread.start()
    self._node_started_event.wait()
  
  def stop(self):
    self._node_stop_event.set()
    self._node_stopped_event.wait()
  
  def inbound_frame(self, frame_data):
    '''Called by subclass when an inbound LocalTalk frame is received.'''
    if len(frame_data) < 3: return  # invalid frame, too short
    destination_node, source_node, llap_type = struct.unpack('>BBB', frame_data[0:3])
    # short-header data frame
    if llap_type == self.LLAP_APPLETALK_SHORT_HEADER:
      try:
        datagram = Datagram.from_short_header_bytes(destination_node, source_node, frame_data[3:])
      except ValueError as e:
        logging.debug('%s failed to parse short-header AppleTalk datagram from LocalTalk frame: %s', str(self), e.args[0])
      else:
        log_datagram_inbound(self.network, self.node, datagram, self)
        self._router.inbound(datagram, self)
    # long-header data frame
    elif llap_type == self.LLAP_APPLETALK_LONG_HEADER:
      try:
        datagram = Datagram.from_long_header_bytes(frame_data[3:])
      except ValueError as e:
        logging.debug('%s failed to parse long-header AppleTalk datagram from LocalTalk frame: %s', str(self), e.args[0])
      else:
        log_datagram_inbound(self.network, self.node, datagram, self)
        self._router.inbound(datagram, self)
    # we've settled on a node address and someone else is asking if they can use it, we say no
    elif llap_type == self.LLAP_ENQ and self._respond_to_enq and self.node and self.node == destination_node:
      self.send_frame(bytes((self.node, self.node, self.LLAP_ACK)))
    else:
      with self._node_lock:
        # someone else has responded that they're on the node address that we want
        if llap_type in (self.LLAP_ENQ, self.LLAP_ACK) and not self.node and self._desired_node == destination_node:
          self._desired_node_attempts = 0
          self._desired_node = self._desired_node_list.pop()
          if not self._desired_node_list:
            self._desired_node_list = list(range(1, 0xFE + 1))
            random.shuffle(self._desired_node_list)
  
  def send_frame(self, frame_data):
    '''Implemented by subclass to send an outbound LocalTalk frame.'''
    raise NotImplementedError('subclass must override "send_frame" method')
  
  def set_node_id(self, node):
    '''Called when a LocalTalk node ID is settled on.  May be overridden by subclass.'''
    self.node = node
  
  def unicast(self, network, node, datagram):
    if network not in (0, self.network): return
    if self.node == 0: return
    log_datagram_unicast(network, node, datagram, self)
    if datagram.destination_network == datagram.source_network and datagram.destination_network in (0, self.network):
      self.send_frame(bytes((node, self.node, self.LLAP_APPLETALK_SHORT_HEADER)) + datagram.as_short_header_bytes())
    else:
      self.send_frame(bytes((node, self.node, self.LLAP_APPLETALK_LONG_HEADER)) + datagram.as_long_header_bytes())
  
  def broadcast(self, datagram):
    if self.node == 0: return
    log_datagram_broadcast(datagram, self)
    self.send_frame(bytes((0xFF, self.node, self.LLAP_APPLETALK_SHORT_HEADER)) + datagram.as_short_header_bytes())
  
  def multicast(self, zone_name, datagram):
    if self.node == 0: return
    log_datagram_multicast(zone_name, datagram, self)
    self.send_frame(bytes((0xFF, self.node, self.LLAP_APPLETALK_SHORT_HEADER)) + datagram.as_short_header_bytes())
  
  def _set_network(self, network):
    logging.info('%s assigned network number %d', str(self), network)
    self.network = self.network_min = self.network_max = network
    self._router.routing_table.set_port_range(self, self.network, self.network)
  
  def set_network_range(self, network_min, network_max):
    if network_min != network_max: raise ValueError('LocalTalk networks are nonextended and cannot be set to a range of networks')
    if self.network: raise ValueError('%s assigned network number %d but already has %d' % (str(self), network_min, self.network))
    self._set_network(network_min)
  
  @staticmethod
  def multicast_address(_):
    return b''  # multicast is not supported on LocalTalk
  
  def _node_run(self):
    if self.network:
      self._set_network(self.network)
      self._router.zone_information_table.add_networks_to_zone(self._seed_zone_name, self.network, self.network)
    self._node_started_event.set()
    while not self._node_stop_event.wait(self.ENQ_INTERVAL):
      send_enq = None
      with self._node_lock:
        if self._desired_node_attempts >= self.ENQ_ATTEMPTS:
          logging.info('%s claiming node address %d', str(self), self._desired_node)
          self.set_node_id(self._desired_node)
          break
        else:
          send_enq = self._desired_node
          self._desired_node_attempts += 1
      if send_enq: self.send_frame(bytes((send_enq, send_enq, self.LLAP_ENQ)))
    self._node_stopped_event.set()
