'''Port that connects to LToUDP.'''

import os
import select
import socket
import struct
from threading import Thread, Event
import time

from . import Port
from .localtalk import LocalTalkPort
from ..datagram import Datagram


LTOUDP_GROUP = '239.192.76.84'  # the last two octets spell 'LT'
LTOUDP_PORT = 1954


class LtoudpPort(Port, LocalTalkPort):
  
  SELECT_TIMEOUT = 0.25  # seconds
  
  def __init__(self, intf_address='0.0.0.0', network=0):
    self.intf_address = intf_address
    self.network = self.network_min = self.network_max = network
    self.node = 0
    self.extended_network = False
    self.router = None
    self.socket = None
    self.sender_id = None
    self.thread = None
    self.started_event = Event()
    self.stop_requested = False
    self.stopped_event = Event()
  
  def start(self, router):
    self.router = router
    self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    self.socket.bind((LTOUDP_GROUP, LTOUDP_PORT))
    self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    #TODO next line crashes out with "OSError: [Errno 19] No such device" if network is not up
    self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                           socket.inet_aton(LTOUDP_GROUP) + socket.inet_aton(self.intf_address))
    self.sender_id = struct.pack('>L', os.getpid())
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
    self.socket.sendto(self.sender_id + packet_data, (LTOUDP_GROUP, LTOUDP_PORT))
  
  def multicast(self, _, datagram):
    if self.node == 0: return
    packet_data = bytes((0xFF, self.node, 1)) + datagram.as_short_header_bytes()
    self.socket.sendto(self.sender_id + packet_data, (LTOUDP_GROUP, LTOUDP_PORT))
  
  def set_network_range(self, network_min, network_max):
    if network_min != network_max: return  # we're a nonextended network, we can't be set to a range of networks
    self.network = self.network_min = self.network_max = network_min
    self.router.routing_table.set_port_range(self, self.network, self.network)
  
  @staticmethod
  def multicast_address(_):
    return b''  # multicast is not supported on LocalTalk
  
  def _run(self):
    
    if self.network: self.set_network_range(self.network, self.network)
    
    self.started_event.set()
    
    self.node = 0
    desired_node = 0xFE
    desired_node_attempts = 0
    last_attempt = time.monotonic()
    
    while not self.stop_requested:
      
      rlist, _, _ = select.select((self.socket,), (), (), self.SELECT_TIMEOUT)
      
      if self.node == 0 and time.monotonic() - last_attempt >= self.ENQ_INTERVAL:
        last_attempt = time.monotonic()
        if desired_node_attempts >= self.ENQ_ATTEMPTS:
          self.node = desired_node
        else:
          self.socket.sendto(self.sender_id + bytes((desired_node, desired_node, self.LLAP_ENQ)), (LTOUDP_GROUP, LTOUDP_PORT))
          desired_node_attempts += 1
      
      if self.socket not in rlist: continue
      
      data, sender_addr = self.socket.recvfrom(65507)
      if len(data) < 7: continue
      if data[0:4] == self.sender_id: continue  #TODO check sender_addr too
      
      # data packet
      if not data[6] & 0x80 and len(data) >= 12:
        self.router.inbound(Datagram.from_llap_packet_bytes(data[4:]), self)
      # we've settled on a node address and someone else is asking if they can use it, we say no
      elif data[6] == self.LLAP_ENQ and self.node and self.node == data[4]:
        self.socket.sendto(self.sender_id + bytes((self.node, self.node, self.LLAP_ACK)), (LTOUDP_GROUP, LTOUDP_PORT))
      # someone else has responded that they're on the node address that we want
      elif data[6] == self.LLAP_ACK and not self.node and desired_node == data[4]:
        desired_node_attempts = 0
        desired_node -= 1
        if desired_node == 0: desired_node = 0xFE  # sure are a lot of addresses in use here, wrap around and search again
    
    self.stopped_event.set()
