'''Port driver for EtherTalk using MACVTAP.'''

from fcntl import ioctl
import os
from queue import Queue
from select import select
import struct
from threading import Thread, Event

from . import EtherTalkPort


class MacvtapPort(EtherTalkPort):
  '''Port driver for EtherTalk using MACVTAP.
  
  To create a MACVTAP for use with this Port:
  # ip link add link eth0 name macvtap0 type macvtap  # this creates /dev/tapX because Xth interface
  # ip link set dev macvtap0 promisc on  # this is important, otherwise we don't get broadcast frames
  
  Then pass 'macvtap0' to the constructor's macvtap parameter.  If left as None, the first macvtap found will be used.
  '''
  
  SELECT_TIMEOUT = 0.25  # seconds
  
  TUNGETIFF = 0x800454D2
  TUNSETIFF = 0x400454CA
  IFF_VNET_HDR = 0x4000
  
  def __init__(self, macvtap_name=None, seed_network_min=0, seed_network_max=0, seed_zone_names=()):
    super().__init__(None, seed_network_min, seed_network_max, seed_zone_names)
    self._reader_thread = None
    self._reader_started_event = Event()
    self._reader_stop_requested = False
    self._reader_stopped_event = Event()
    self._macvtap_name = macvtap_name
    self._fp = None
    self._writer_thread = None
    self._writer_started_event = Event()
    self._writer_stop_flag = object()
    self._writer_stopped_event = Event()
    self._writer_queue = Queue()
  
  def short_str(self):
    return self._macvtap_name
  
  __str__ = short_str
  __repr__ = short_str
  
  def start(self, router):
    
    if not os.path.exists('/sys/class/net/'): raise FileNotFoundError("can't find /sys/class/net/")
    if not self._macvtap_name:
      if macvtaps := [i for i in os.listdir('/sys/class/net/') if i.startswith('macvtap')]:
        self._macvtap_name = macvtaps[0]
      else:
        raise FileNotFoundError("can't find any macvtaps")
    
    address_path = '/sys/class/net/%s/address' % self._macvtap_name
    if not os.path.exists(address_path): raise FileNotFoundError("can't find %s" % address_path)
    with open(address_path, 'r') as fp: self._hw_addr = bytes(int(i, 16) for i in fp.read().strip().split(':'))
    ifindex_path = '/sys/class/net/%s/ifindex' % self._macvtap_name
    if not os.path.exists(ifindex_path): raise FileNotFoundError("can't find %s" % ifindex_path)
    with open(ifindex_path, 'r') as fp: tap_device = '/dev/tap%d' % int(fp.read())
    if not os.path.exists(tap_device): raise FileNotFoundError("can't find %s" % tap_device)
    self._fp = os.open(tap_device, os.O_RDWR)
    
    # Necessary to clear IFF_VNET_HDR or else we'd get a virtio_net_hdr struct before every frame
    ifreq = bytearray(40)
    ioctl(self._fp, self.TUNGETIFF, ifreq)
    ifreq[16:18] = struct.pack('H', struct.unpack('H', ifreq[16:18])[0] & ~self.IFF_VNET_HDR)
    ioctl(self._fp, self.TUNSETIFF, ifreq)
    
    super().start(router)
    self._reader_thread = Thread(target=self._reader_run)
    self._reader_thread.start()
    self._writer_thread = Thread(target=self._writer_run)
    self._writer_thread.start()
    self._reader_started_event.wait()
    self._writer_started_event.wait()
  
  def stop(self):
    self._reader_stop_requested = True
    self._writer_queue.put(self._writer_stop_flag)
    self._reader_stopped_event.wait()
    self._writer_stopped_event.wait()
    os.close(self._fp)
    super().stop()
  
  def send_frame(self, frame_data):
    self._writer_queue.put(frame_data)
  
  def _reader_run(self):
    self._reader_started_event.set()
    while not self._reader_stop_requested:
      rlist, _, _ = select((self._fp,), (), (), self.SELECT_TIMEOUT)
      if self._fp not in rlist: continue
      self.inbound_frame(os.read(self._fp, 65535))
    self._reader_stopped_event.set()
  
  def _writer_run(self):
    self._writer_started_event.set()
    while True:
      frame_data = self._writer_queue.get()
      if frame_data is self._writer_stop_flag: break
      select((), (self._fp,), ())
      os.write(self._fp, frame_data)
    self._writer_stopped_event.set()
