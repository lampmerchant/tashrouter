'''Port that connects to LocalTalk via TashTalk on a serial port.'''

from threading import Thread, Event, Lock
import time

import serial

from . import Port
from ..datagram import Datagram


LT_FCS_LUT = (
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


class FcsCalculator:
  '''Utility class to calculate the FCS (frame check sequence) of a LocalTalk frame.'''
  
  def __init__(self):
    self.reg = 0
    self.reset()
  
  def reset(self):
    '''Reset the FCS calculator as though no data had been fed into it.'''
    self.reg = 0xFFFF
  
  def feed_byte(self, byte):
    '''Feed a single byte (an integer between 0 and 255) into the FCS calculator.'''
    index = (self.reg & 0xFF) ^ byte
    self.reg = LT_FCS_LUT[index] ^ (self.reg >> 8)
  
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


class TashTalkPort(Port):
  
  SERIAL_TIMEOUT = 0.25  # seconds
  ENQ_INTERVAL = 0.25  # seconds
  ENQ_ATTEMPTS = 8
  
  LLAP_ENQ = 0x81
  LLAP_ACK = 0x82
  
  def __init__(self, serial_port, network=0):
    self.serial_obj = serial.Serial(port=serial_port, baudrate=1000000, rtscts=True, timeout=self.SERIAL_TIMEOUT)
    self.network = self.network_min = self.network_max = network
    self.node = 0
    self.extended_network = False
    self.serial_lock = Lock()
    self.router = None
    self.thread = None
    self.started_event = Event()
    self.stop_requested = False
    self.stopped_event = Event()
  
  def start(self, router):
    self.router = router
    self.thread = Thread(target=self._run)
    self.thread.start()
    self.started_event.wait()
  
  def stop(self):
    self.stop_requested = True
    self.stopped_event.wait()
  
  def send(self, network, node, datagram):
    if network not in (0, self.network): return
    if self.node == 0: return
    if datagram.destination_network == datagram.source_network and datagram.destination_network in (0, self.network):
      packet_data = bytes((node, self.node, 1)) + datagram.as_short_header_bytes()
    else:
      packet_data = bytes((node, self.node, 2)) + datagram.as_long_header_bytes()
    fcs = FcsCalculator()
    fcs.feed(packet_data)
    with self.serial_lock:
      self.serial_obj.write(b'\x01')
      self.serial_obj.write(packet_data)
      self.serial_obj.write(bytes((fcs.byte1(), fcs.byte2())))
  
  def multicast(self, _, datagram):
    if self.node == 0: return
    packet_data = bytes((0xFF, self.node, 1)) + datagram.as_short_header_bytes()
    fcs = FcsCalculator()
    fcs.feed(packet_data)
    with self.serial_lock:
      self.serial_obj.write(b'\x01')
      self.serial_obj.write(packet_data)
      self.serial_obj.write(bytes((fcs.byte1(), fcs.byte2())))
  
  def set_network_range(self, network_min, network_max):
    if network_min != network_max: return  # we're a nonextended network, we can't be set to a range of networks
    self.network = self.network_min = self.network_max = network_min
    self.router.routing_table.set_port_range(self, self.network, self.network)
  
  @staticmethod
  def multicast_address(_):
    return b''  # multicast is not supported on LocalTalk
  
  @classmethod
  def enq_frame_cmd(cls, desired_node_address):
    fcs = FcsCalculator()
    fcs.feed_byte(desired_node_address)
    fcs.feed_byte(desired_node_address)
    fcs.feed_byte(cls.LLAP_ENQ)
    return bytes((0x01, desired_node_address, desired_node_address, cls.LLAP_ENQ, fcs.byte1(), fcs.byte2()))
  
  @staticmethod
  def set_node_address_cmd(desired_node_address):
    if not 1 <= desired_node_address <= 254: raise ValueError('node address %d not between 1 and 254' % desired_node_address)
    retval = bytearray(33)
    retval[0] = 0x02
    byte, bit = divmod(desired_node_address, 8)
    retval[byte + 1] = 1 << bit
    return bytes(retval)
  
  def _run(self):
    
    if self.network: self.set_network_range(self.network, self.network)
    
    self.started_event.set()
    
    with self.serial_lock:
      self.serial_obj.write(b'\0' * 1024)  # make sure TashTalk is in a known state, first of all
      self.serial_obj.write(b'\x02' + (b'\0' * 32))  # set node IDs bitmap to zeroes so we don't respond to any RTSes or ENQs yet
      self.serial_obj.write(b'\x03\0')  # turn off optional TashTalk features
    
    self.node = 0
    desired_node = 0xFE
    desired_node_attempts = 0
    last_attempt = time.monotonic()
    
    fcs = FcsCalculator()
    buf = bytearray(605)
    buf_ptr = 0
    escaped = False
    
    while not self.stop_requested:
      
      for byte in self.serial_obj.read(16384):
        if not escaped and byte == 0x00:
          escaped = True
          continue
        elif escaped:
          escaped = False
          if byte == 0xFF:  # literal 0x00 byte
            byte = 0x00
          else:
            if byte == 0xFD and fcs.is_okay() and buf_ptr >= 5:
              # data packet
              if buf_ptr >= 10 and not buf[2] & 0x80:
                self.router.inbound(Datagram.from_llap_packet_bytes(buf[:buf_ptr - 2]), self)
              # someone else has responded that they're on the node address that we want
              elif buf[2] == self.LLAP_ACK and not self.node and desired_node == buf[0]:
                desired_node_attempts = 0
                desired_node -= 1
                if desired_node == 0: desired_node = 0xFE  # sure are a lot of addresses in use here, wrap around and search again
            fcs.reset()
            buf_ptr = 0
            continue
        if buf_ptr < len(buf):
          fcs.feed_byte(byte)
          buf[buf_ptr] = byte
          buf_ptr += 1
      
      if self.node == 0 and time.monotonic() - last_attempt >= self.ENQ_INTERVAL:
        last_attempt = time.monotonic()
        if desired_node_attempts >= self.ENQ_ATTEMPTS:
          with self.serial_lock: self.serial_obj.write(self.set_node_address_cmd(desired_node))
          self.node = desired_node
        else:
          with self.serial_lock: self.serial_obj.write(self.enq_frame_cmd(desired_node))
          desired_node_attempts += 1
    
    self.stopped_event.set()
