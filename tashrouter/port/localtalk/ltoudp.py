'''Port that connects to LToUDP.'''

import os
import select
import socket
import struct
from threading import Thread, Event

from . import LocalTalkPort


class LtoudpPort(LocalTalkPort):
  '''Port that connects to LToUDP.'''
  
  LTOUDP_GROUP = '239.192.76.84'  # the last two octets spell 'LT'
  LTOUDP_PORT = 1954
  
  SELECT_TIMEOUT = 0.25  # seconds
  
  def __init__(self, intf_address='0.0.0.0', network=0):
    super().__init__(network=network, respond_to_enq=True)
    self._intf_address = intf_address
    self._socket = None
    self._sender_id = None
    self._thread = None
    self._started_event = Event()
    self._stop_requested = False
    self._stopped_event = Event()
  
  def start(self, router):
    super().start(router)
    self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    self._socket.bind((self.LTOUDP_GROUP, self.LTOUDP_PORT))
    self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    #TODO next line crashes out with "OSError: [Errno 19] No such device" if network is not up
    self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                           socket.inet_aton(self.LTOUDP_GROUP) + socket.inet_aton(self._intf_address))
    self._sender_id = struct.pack('>L', os.getpid())
    self._thread = Thread(target=self._run)
    self._thread.start()
    self._started_event.wait()
  
  def stop(self):
    super().stop()
    self._stop_requested = True
    self._stopped_event.wait()
  
  def send_packet(self, packet_data):
    self._socket.sendto(self._sender_id + packet_data, (self.LTOUDP_GROUP, self.LTOUDP_PORT))
  
  def _run(self):
    self._started_event.set()
    while not self._stop_requested:
      rlist, _, _ = select.select((self._socket,), (), (), self.SELECT_TIMEOUT)
      if self._socket not in rlist: continue
      data, sender_addr = self._socket.recvfrom(65507)
      if len(data) < 7: continue
      if data[0:4] == self._sender_id: continue  #TODO check sender_addr too
      self.inbound_packet(data[4:])
    self._stopped_event.set()
