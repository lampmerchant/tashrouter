'''Classes for virtual EtherTalk networks.'''

from collections import deque
from threading import Lock

from . import EtherTalkPort


class VirtualEtherTalkPort(EtherTalkPort):
  '''Virtual EtherTalk Port.'''
  
  def __init__(self, virtual_network, hw_addr, short_str=None, seed_network_min=0, seed_network_max=0, seed_zone_names=()):
    super().__init__(hw_addr, seed_network_min, seed_network_max, seed_zone_names)
    self._virtual_network = virtual_network
    self._short_str = short_str or 'Virtual'
  
  def short_str(self): return self._short_str
  __str__ = short_str
  __repr__ = short_str
  
  def start(self, router):
    self._virtual_network.plug(self._hw_addr, self.inbound_frame)
    super().start(router)
  
  def stop(self):
    super().stop()
    self._virtual_network.unplug(self._hw_addr)
  
  def send_frame(self, frame_data):
    self._virtual_network.send_frame(frame_data, self._hw_addr)


class VirtualEtherTalkNetwork:
  '''Virtual EtherTalk network.'''
  
  def __init__(self):
    self._plugged = {}  # ethernet address -> receive frame function
    self._lock = Lock()
  
  def plug(self, hw_addr, recv_func):
    with self._lock: self._plugged[hw_addr] = recv_func
  
  def unplug(self, hw_addr):
    with self._lock: self._plugged.pop(hw_addr)
  
  def send_frame(self, frame_data, recv_hw_addr):
    if not frame_data: return
    is_multicast = True if frame_data[0] & 0x01 else False
    function_calls = deque()
    with self._lock:
      for hw_addr, func in self._plugged.items():
        if hw_addr == recv_hw_addr: continue
        if is_multicast or frame_data[0:6] == hw_addr: function_calls.append((func, frame_data))
    for func, frame_data in function_calls: func(frame_data)
