'''Name Information Service.'''

from collections import deque
from dataclasses import dataclass
from io import BytesIO
from queue import Queue
import re
import struct
from threading import Thread, Event, Lock
import time

from . import Service
from ..datagram import Datagram


ATALK_LCASE = b'abcdefghijklmnopqrstuvwxyz\x88\x8A\x8B\x8C\x8D\x8E\x96\x9A\x9B\x9F\xBE\xBF\xCF'
ATALK_LCASE_VALUES = tuple(ATALK_LCASE)
ATALK_UCASE = b'ABCDEFGHIJKLMNOPQRSTUVWXYZ\xCB\x80\xCC\x81\x82\x83\x84\x85\xCD\x86\xAE\xAF\xCE'
ATALK_UCASE_VALUES = tuple(ATALK_UCASE)
RE_ESCAPABLES = b' #$&()*+-.?[\\]^{|}~'
RE_ESCAPABLES_VALUES = tuple(RE_ESCAPABLES)


def _ucase_char(byte):
  try:
    return ATALK_UCASE[ATALK_LCASE.index(byte)]
  except ValueError:
    return byte


def ucase(b):
  '''Convert a bytes-like to uppercase using the correspondence table laid out in IA Appendix D.'''
  return bytes(_ucase_char(byte) for byte in b)


def _nbp_pattern_byte_to_re(byte, allow_wildcards=True):
  if byte == 0xC5 and allow_wildcards:  # the rarely-used ~= wildcard
    return b'.*'
  elif byte in ATALK_LCASE_VALUES:
    return bytes((0x5B, byte, ATALK_UCASE_VALUES[ATALK_LCASE_VALUES.index(byte)], 0x5D))
  elif byte in ATALK_UCASE_VALUES:
    return bytes((0x5B, ATALK_LCASE_VALUES[ATALK_UCASE_VALUES.index(byte)], byte, 0x5D))
  elif byte in RE_ESCAPABLES_VALUES:
    return bytes((0x5C, byte))
  else:
    return bytes((byte,))


def nbp_pattern_to_reo(pattern):
  '''Convert an NBP pattern (for an object or type) to a compiled regular expression.'''
  if pattern == b'=':
    return re.compile(b'^.*$')
  else:
    return re.compile(b'^%s$' % b''.join(_nbp_pattern_byte_to_re(byte) for byte in pattern))


def nbp_pattern_to_reo_zone(pattern):
  '''Convert an NBP pattern (for a zone) to a compiled regular expression.'''
  return re.compile(b'^(?:\\*|%s)$' % b''.join(_nbp_pattern_byte_to_re(byte, False) for byte in pattern))


class LkupRouter:
  '''Device to remember sent LkUps and the proper destination of LkUp-Replies.'''
  
  LKUP_TIMEOUT = 30  # seconds
  TIMEOUT_INTERVAL = 1  # seconds
  
  def __init__(self):
    self._tuples = deque()  # (timeout, nbp ID, object reo, type reo, zone reo, network, node, socket)
    self._lock = Lock()
    self._thread = None
    self._started_event = Event()
    self._stop_event = Event()
    self._stopped_event = Event()
  
  def remember_lkup(self, nbp_id, object_field, type_field, zone_field, network, node, socket):
    '''Take note of a LkUp we're sending out for potential later retrieval.'''
    if not self._started_event.is_set(): return
    object_reo = nbp_pattern_to_reo(object_field)
    type_reo = nbp_pattern_to_reo(type_field)
    zone_reo = nbp_pattern_to_reo_zone(zone_field)
    later = time.monotonic() + self.LKUP_TIMEOUT
    with self._lock: self._tuples.append((later, nbp_id, object_reo, type_reo, zone_reo, network, node, socket))
  
  def find_destinations(self, nbp_id, nbp_tuple):
    '''Find intended destinations for an NBP tuple directly received in a LkUp-Reply.'''
    destinations = deque()
    with self._lock:
      new_tuples = deque()
      for timeout, tuple_nbp_id, object_reo, type_reo, zone_reo, network, node, socket in self._tuples:
        if (tuple_nbp_id == nbp_id and object_reo.match(nbp_tuple.object_field) and type_reo.match(nbp_tuple.type_field)
            and zone_reo.match(nbp_tuple.zone_field) and (nbp_tuple.network, nbp_tuple.node) != (network, node)):
          destinations.append((network, node, socket))
        else:
          new_tuples.append((timeout, nbp_id, object_reo, type_reo, zone_reo, network, node, socket))
      self._tuples = new_tuples
    yield from destinations
  
  def start(self):
    self._thread = Thread(target=self._run)
    self._thread.start()
    self._started_event.wait()
  
  def stop(self):
    self._stop_event.set()
    self._stopped_event.wait()
  
  def _run(self):
    self._started_event.set()
    while True:
      if self._stop_event.wait(timeout=self.TIMEOUT_INTERVAL): break
      with self._lock:
        if self._tuples:
          new_tuples = deque()
          now = time.monotonic()
          for timeout, nbp_id, object_reo, type_reo, zone_reo, network, node, socket in self._tuples:
            if now < timeout: new_tuples.append((timeout, nbp_id, object_reo, type_reo, zone_reo, network, node, socket))
          self._tuples = new_tuples
    self._stopped_event.set()


@dataclass
class NbpTuple:
  '''Represents a single tuple in an NBP datagram.'''
  
  MAX_FIELD_LENGTH = 32
  
  network: int
  node: int
  socket: int
  enumerator: int
  object_field: bytes
  type_field: bytes
  zone_field: bytes
  
  @classmethod
  def _read_field(cls, bio, field_name):
    length = bio.read(1)
    if len(length) != 1: raise ValueError('incomplete tuple - missing %s field length' % field_name)
    length = length[0]
    if length > cls.MAX_FIELD_LENGTH:
      raise ValueError('invalid tuple - %s length %d over maximum of %d' % (field_name, length, cls.MAX_FIELD_LENGTH))
    field = bio.read(length)
    if len(field) != length: raise ValueError('incomplete tuple - truncated %s field' % field_name)
    return field
  
  @classmethod
  def _parse_single(cls, bio):
    header = bio.read(5)
    if not header: return None
    if len(header) < 5: raise ValueError('incomplete tuple - partial header')
    network, node, socket, enumerator = struct.unpack('>HBBB', header)
    object_field = cls._read_field(bio, 'object')
    type_field = cls._read_field(bio, 'type')
    zone_field = cls._read_field(bio, 'zone') or b'*'
    return cls(network=network,
               node=node,
               socket=socket,
               enumerator=enumerator,
               object_field=object_field,
               type_field=type_field,
               zone_field=zone_field)
  
  @classmethod
  def from_bytes(cls, b, expected_count):
    '''Parse and yield tuples from a byte string.'''
    bio = BytesIO(b)
    actual_count = 0
    cur_tuple = cls._parse_single(bio)
    while cur_tuple:
      yield cur_tuple
      actual_count += 1
      cur_tuple = cls._parse_single(bio)
    if actual_count != expected_count: raise IndexError('parsed %d tuples, expected %d' % (actual_count, expected_count))
  
  def as_bytes(self):
    '''Convert this tuple to a byte string.'''
    return b''.join((struct.pack('>HBBBB', self.network, self.node, self.socket, self.enumerator, len(self.object_field)),
                     self.object_field,
                     struct.pack('>B', len(self.type_field)),
                     self.type_field,
                     struct.pack('>B', len(self.zone_field)),
                     self.zone_field))


class NameInformationService(Service):
  '''A Service that implements Name Binding Protocol (NBP).'''
  
  NBP_SAS = 2
  NBP_DDP_TYPE = 2
  
  NBP_CTRL_BRRQ = 1
  NBP_CTRL_LKUP = 2
  NBP_CTRL_LKUP_REPLY = 3
  NBP_CTRL_FWDREQ = 4
  
  def __init__(self, route_lkup_replies=False):
    self._thread = None
    self._queue = Queue()
    self._stop_flag = object()
    self._started_event = Event()
    self._stopped_event = Event()
    self._lkup_router = LkupRouter() if route_lkup_replies else None
  
  def start(self, router):
    self._thread = Thread(target=self._run, args=(router,))
    self._thread.start()
    self._started_event.wait()
    if self._lkup_router: self._lkup_router.start()
  
  def stop(self):
    self._queue.put(self._stop_flag)
    if self._lkup_router: self._lkup_router.stop()
    self._stopped_event.wait()
  
  def _run(self, router):
    
    self._started_event.set()
    
    while True:
      
      item = self._queue.get()
      if item is self._stop_flag: break
      datagram, rx_port = item
      
      if datagram.ddp_type != self.NBP_DDP_TYPE: continue
      if len(datagram.data) < 2: continue
      func_tuple_count, nbp_id = struct.unpack('>BB', datagram.data[:2])
      func = func_tuple_count >> 4
      tuple_count = func_tuple_count & 0xF
      try:
        tuples = tuple(NbpTuple.from_bytes(datagram.data[2:], tuple_count))
      except (IndexError, ValueError):
        continue
      
      if func == self.NBP_CTRL_BRRQ:
        
        if len(tuples) != 1: continue
        zone_field = tuples[0].zone_field
        
        # if zone is *, try to sub in the zone name associated with the nonextended network whence the BrRq comes
        if zone_field == b'*':
          if rx_port.extended_network: continue  # BrRqs from extended networks must provide zone name
          if rx_port.network:
            entry, _ = router.routing_table.get_by_network(rx_port.network)
            if entry:
              try:
                zones = router.zone_information_table.zones_in_network_range(entry.network_min)
              except ValueError:
                pass
              else:
                if len(zones) == 1: zone_field = zones[0]  # there should not be more than one zone
        
        # if zone is still *, just broadcast a LkUp on the requesting network and call it done
        if zone_field == b'*':
          if self._lkup_router:
            self._lkup_router.remember_lkup(nbp_id, tuples[0].object_field, tuples[0].type_field, zone_field, tuples[0].network, 
                                            tuples[0].node, tuples[0].socket)
          rx_port.broadcast(Datagram(hop_count=0,
                                     destination_network=0x0000,
                                     source_network=rx_port.network,
                                     destination_node=0xFF,
                                     source_node=rx_port.node,
                                     destination_socket=self.NBP_SAS,
                                     source_socket=self.NBP_SAS,
                                     ddp_type=self.NBP_DDP_TYPE,
                                     data=struct.pack('>BB', (self.NBP_CTRL_LKUP << 4) | 1, nbp_id) + tuples[0].as_bytes()))
        # we know the zone, so multicast LkUps to directly-connected networks and send FwdReqs to non-directly-connected ones
        else:
          entries = set(router.routing_table.get_by_network(zone_network)
                        for zone_network in router.zone_information_table.networks_in_zone(zone_field))
          entries.discard((None, None))
          for entry, _ in entries:
            if entry.distance == 0:
              if self._lkup_router:
                self._lkup_router.remember_lkup(nbp_id, tuples[0].object_field, tuples[0].type_field, zone_field, 
                                                tuples[0].network, tuples[0].node, tuples[0].socket)
              entry.port.multicast(zone_field, Datagram(hop_count=0,
                                                        destination_network=0x0000,
                                                        source_network=entry.port.network,
                                                        destination_node=0xFF,
                                                        source_node=entry.port.node,
                                                        destination_socket=self.NBP_SAS,
                                                        source_socket=self.NBP_SAS,
                                                        ddp_type=self.NBP_DDP_TYPE,
                                                        data=struct.pack('>BB', (self.NBP_CTRL_LKUP << 4) | 1, nbp_id)
                                                        + tuples[0].as_bytes()))
            else:
              router.route(Datagram(hop_count=0,
                                    destination_network=entry.network_min,
                                    source_network=0,
                                    destination_node=0x00,
                                    source_node=0,
                                    destination_socket=self.NBP_SAS,
                                    source_socket=self.NBP_SAS,
                                    ddp_type=self.NBP_DDP_TYPE,
                                    data=struct.pack('>BB', (self.NBP_CTRL_FWDREQ << 4) | 1, nbp_id) + tuples[0].as_bytes()))
        
      elif func == self.NBP_CTRL_FWDREQ:
        
        if len(tuples) != 1: continue
        entry, _ = router.routing_table.get_by_network(datagram.destination_network)
        if entry is None or entry.distance != 0: continue  # FwdReq thinks we're directly connected to this network but we're not
        if self._lkup_router:
          self._lkup_router.remember_lkup(nbp_id, tuples[0].object_field, tuples[0].type_field, tuples[0].zone_field, 
                                          tuples[0].network, tuples[0].node, tuples[0].socket)
        entry.port.multicast(tuples[0].zone_field, Datagram(hop_count=0,
                                                            destination_network=0x0000,
                                                            source_network=entry.port.network,
                                                            destination_node=0xFF,
                                                            source_node=entry.port.node,
                                                            destination_socket=self.NBP_SAS,
                                                            source_socket=self.NBP_SAS,
                                                            ddp_type=self.NBP_DDP_TYPE,
                                                            data=struct.pack('>BB', (self.NBP_CTRL_LKUP << 4) | 1, nbp_id)
                                                            + tuples[0].as_bytes()))
        
      elif func == self.NBP_CTRL_LKUP_REPLY:
        
        # in a standards-compliant world, the router would never receive a LkUp-Reply directly, but some NBP implementations are
        # braindead and send their LkUp-Replies to the datagram's source address rather than the address in the NBP tuple -
        # LkupRouter exists to handle such conditions without forcing the router to do the wrong thing and fake the source address
        if self._lkup_router:
          for nbp_tuple in tuples:
            for network, node, socket in self._lkup_router.find_destinations(nbp_id, nbp_tuple):
              router.route(Datagram(hop_count=0,
                                    destination_network=network,
                                    source_network=nbp_tuple.network,
                                    destination_node=node,
                                    source_node=nbp_tuple.node,
                                    destination_socket=socket,
                                    source_socket=nbp_tuple.socket,
                                    ddp_type=self.NBP_DDP_TYPE,
                                    data=struct.pack('>BB', (self.NBP_CTRL_LKUP_REPLY << 4) | 1, nbp_id) + nbp_tuple.as_bytes(),
                                    header_type=Datagram.HEADER_TYPE_LONG),
                           originating=False)  # header must be long since originating=False means hop count will be 1
    
    self._stopped_event.set()
  
  def inbound(self, datagram, rx_port):
    self._queue.put((datagram, rx_port))
