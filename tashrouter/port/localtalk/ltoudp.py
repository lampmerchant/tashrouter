'''Port that connects to LToUDP.'''

import errno
import os
import select
import socket
import struct
from threading import Thread, Event
import time

from . import LocalTalkPort
from ...netlog import log_localtalk_frame_inbound, log_localtalk_frame_outbound


class LtoudpPort(LocalTalkPort):
  '''Port that connects to LToUDP.'''
  
  LTOUDP_GROUP = '239.192.76.84'  # the last two octets spell 'LT'
  LTOUDP_PORT = 1954
  
  DEFAULT_INTF_ADDRESS = '0.0.0.0'
  
  SELECT_TIMEOUT = 0.25  # seconds
  NETWORK_UP_RETRY_TIMEOUT = 1  # seconds
  NETWORK_UP_RETRY_COUNT = 10
  
  def __init__(self, intf_address=DEFAULT_INTF_ADDRESS, **kwargs):
    super().__init__(respond_to_enq=True, **kwargs)
    self._intf_address = intf_address
    self._socket = None
    self._sender_id = None
    self._thread = None
    self._started_event = Event()
    self._stop_requested = False
    self._stopped_event = Event()
  
  def short_str(self):
    if self._intf_address == self.DEFAULT_INTF_ADDRESS:
      return 'LToUDP'
    else:
      return self._intf_address
  
  __str__ = short_str
  __repr__ = short_str
  
  def start(self, router):
    self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, 'SO_REUSEPORT'): self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    self._socket.bind((self._intf_address, self.LTOUDP_PORT))
    self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    for attempt in range(self.NETWORK_UP_RETRY_COUNT):
      try:
        # this raises "OSError: [Errno 19] No such device" if network is not up, so build in some retry logic
        self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                socket.inet_aton(self.LTOUDP_GROUP) + socket.inet_aton(self._intf_address))
        break
      except OSError as e:
        if e.errno != errno.ENODEV or attempt + 1 == self.NETWORK_UP_RETRY_COUNT: raise
        time.sleep(self.NETWORK_UP_RETRY_TIMEOUT)
    self._sender_id = struct.pack('>L', os.getpid())
    super().start(router)
    self._thread = Thread(target=self._run)
    self._thread.start()
    self._started_event.wait()
  
  def stop(self):
    super().stop()
    self._stop_requested = True
    self._stopped_event.wait()
  
  def send_frame(self, frame_data):
    log_localtalk_frame_outbound(frame_data, self)
    self._socket.sendto(self._sender_id + frame_data, (self.LTOUDP_GROUP, self.LTOUDP_PORT))
  
  def _run(self):
    self._started_event.set()
    while not self._stop_requested:
      rlist, _, _ = select.select((self._socket,), (), (), self.SELECT_TIMEOUT)
      if self._socket not in rlist: continue
      data, sender_addr = self._socket.recvfrom(65507)
      if len(data) < 7: continue
      if data[0:4] == self._sender_id: continue  #TODO check sender_addr too
      log_localtalk_frame_inbound(data[4:], self)
      self.inbound_frame(data[4:])
    self._stopped_event.set()
