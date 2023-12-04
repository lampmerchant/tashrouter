'''Table of routing information.'''

import dataclasses
from collections import deque
from threading import Lock

from ..port import Port


@dataclasses.dataclass(frozen=True)
class RoutingTableEntry:
  '''An entry in a routing table for a single network, used to route Datagrams to Ports.'''
  
  network_min: int
  network_max: int
  distance: int
  port: Port
  next_network: int
  next_node: int


class RoutingTable:
  '''A Router's routing table.'''
  
  STATE_GOOD = 1
  STATE_SUS = 2
  STATE_BAD = 3
  STATE_WORST = 4
  
  def __init__(self, zone_information_table):
    self._zone_information_table = zone_information_table
    self._entry_by_network = {}
    self._state_by_entry = {}
    self._lock = Lock()
  
  def __contains__(self, entry):
    with self._lock:
      return True if entry in self._state_by_entry else False
  
  def __iter__(self):
    with self._lock:
      retval = deque(self._state_by_entry.keys())
    yield from retval
  
  def get_by_network(self, network):
    '''Look up and return an entry in this RoutingTable by network number.  Returns (entry, is_bad).'''
    with self._lock:
      entry = self._entry_by_network.get(network)
      if entry is None: return None, None
      return entry, True if self._state_by_entry[entry] in (self.STATE_BAD, self.STATE_WORST) else False
  
  def mark_bad(self, network_min, network_max):
    '''If this RoutingTable has an entry with the given network range, mark it bad.  Return True if it existed, else False.'''
    with self._lock:
      cur_entries = set(self._entry_by_network.get(network) for network in range(network_min, network_max + 1))
      if len(cur_entries) != 1: return False
      cur_entry = cur_entries.pop()  # this is either None or an entry with a coincident range to the new one
      if not cur_entry: return False
      if self._state_by_entry[cur_entry] != self.STATE_WORST: self._state_by_entry[cur_entry] = self.STATE_BAD
      return True
  
  def consider(self, entry):
    '''Consider a new entry for addition to the table.  Return True if added, False if not.'''
    
    with self._lock:
      if entry in self._state_by_entry:
        self._state_by_entry[entry] = self.STATE_GOOD
        return True
      cur_entries = set(self._entry_by_network.get(network) for network in range(entry.network_min, entry.network_max + 1))
      if len(cur_entries) != 1: return False  # this network range overlaps one that's already defined, can't do anything with it
      cur_entry = cur_entries.pop()
      
      # range currently undefined, add new entry to the table
      if cur_entry is None:
        pass
      # range fully defined by an entry that is either bad or further away, add new entry to the table
      elif cur_entry.distance >= entry.distance or self._state_by_entry[cur_entry] in (self.STATE_BAD, self.STATE_WORST):
        pass
      # range fully defined by an entry representing a route that is now further than we thought, add new entry to the table
      elif (cur_entry.next_network, cur_entry.next_node, cur_entry.port) == (entry.next_network, entry.next_node, entry.port):
        pass
      # range fully defined by a good entry that is closer than the new one, ignore new entry
      else:
        return False
      
      if cur_entry: self._state_by_entry.pop(cur_entry)
      self._state_by_entry[entry] = self.STATE_GOOD
      for network in range(entry.network_min, entry.network_max + 1): self._entry_by_network[network] = entry
      return True
  
  def age(self):
    '''Age the RoutingTableEntries in this RoutingTable.'''
    entries_to_delete = set()
    networks_to_delete = deque()
    with self._lock:
      for entry in set(self._entry_by_network.values()):
        if self._state_by_entry[entry] == self.STATE_WORST:
          entries_to_delete.add(entry)
          self._state_by_entry.pop(entry)
        elif self._state_by_entry[entry] == self.STATE_BAD:
          self._state_by_entry[entry] = self.STATE_WORST
        elif self._state_by_entry[entry] == self.STATE_SUS:
          self._state_by_entry[entry] = self.STATE_BAD
        elif self._state_by_entry[entry] == self.STATE_GOOD and entry.distance != 0:
          self._state_by_entry[entry] = self.STATE_SUS
      for network, entry in self._entry_by_network.items():
        if entry in entries_to_delete: networks_to_delete.append(network)
      for network in networks_to_delete: self._entry_by_network.pop(network)
      self._zone_information_table.remove_networks(networks_to_delete)
  
  def entries(self):
    '''Yield entries from this RoutingTable along with their badness state.'''
    with self._lock: retval = deque(self._state_by_entry.items())
    for entry, state in retval: yield entry, True if state in (self.STATE_BAD, self.STATE_WORST) else False
  
  def set_port_range(self, port, network_min, network_max):
    '''Set the network range for a given port, unsetting any previous entries in the table that defined it.'''
    entries_to_delete = set()
    networks_to_delete = deque()
    with self._lock:
      for network, entry in self._entry_by_network.items():
        if entry.port is port and entry.distance == 0:
          entries_to_delete.add(entry)
          networks_to_delete.append(network)
      for entry in entries_to_delete: self._state_by_entry.pop(entry)
      for network in networks_to_delete: self._entry_by_network.pop(network)
      self._zone_information_table.remove_networks(networks_to_delete)
      entry = RoutingTableEntry(network_min=network_min,
                                network_max=network_max,
                                distance=0,
                                port=port,
                                next_network=0,
                                next_node=0)
      for network in range(network_min, network_max + 1): self._entry_by_network[network] = entry
      self._state_by_entry[entry] = self.STATE_GOOD
