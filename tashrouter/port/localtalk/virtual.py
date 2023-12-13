'''Classes for virtual LocalTalk networks.'''

from collections import deque
from threading import Lock

from . import LocalTalkPort
from ...netlog import log_localtalk_frame_inbound, log_localtalk_frame_outbound


class VirtualLocalTalkPort(LocalTalkPort):
  '''Virtual LocalTalk Port.'''
  
  def __init__(self, virtual_network, short_str=None, seed_network=0, seed_zone_name=None):
    super().__init__(seed_network=seed_network, seed_zone_name=seed_zone_name, respond_to_enq=True)
    self._virtual_network = virtual_network
    self._short_str = short_str or 'Virtual'
  
  def short_str(self): return self._short_str
  __str__ = short_str
  __repr__ = short_str
  
  def _recv_frame(self, frame_data):
    log_localtalk_frame_inbound(frame_data, self)
    self.inbound_frame(frame_data)
  
  def start(self, router):
    self._virtual_network.plug(self._recv_frame)
    super().start(router)
  
  def stop(self):
    super().stop()
    self._virtual_network.unplug(self._recv_frame)
  
  def send_frame(self, frame_data):
    log_localtalk_frame_outbound(frame_data, self)
    self._virtual_network.send_frame(frame_data, self._recv_frame)


class VirtualLocalTalkNetwork:
  '''Virtual LocalTalk network.'''
  
  def __init__(self):
    self._plugged = deque()
    self._lock = Lock()
  
  def plug(self, recv_func):
    with self._lock: self._plugged.append(recv_func)
  
  def unplug(self, recv_func):
    with self._lock: self._plugged.remove(recv_func)
  
  def send_frame(self, frame_data, recv_func):
    function_calls = deque()
    with self._lock:
      for func in self._plugged:
        if func == recv_func: continue
        function_calls.append((func, frame_data))
    for func, frame_data in function_calls: func(frame_data)
