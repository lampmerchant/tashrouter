'''The heart of this whole affair.'''

from .routing_table import RoutingTable
from .zone_information_table import ZoneInformationTable


class Router:
  '''A router, a device which sends Datagrams to Ports and runs Services.'''
  
  def __init__(self, ports, services, seed_zones):
    self.ports = ports
    self.services = services
    self.zone_information_table = ZoneInformationTable()
    for zone_name, networks in seed_zones.items(): self.zone_information_table.add_networks_to_zone(zone_name, networks)
    self._services_by_sas = {}
    for sas, service in self.services:
      if sas is not None: self._services_by_sas[sas] = service
    self.routing_table = RoutingTable(self.zone_information_table)
  
  def _deliver(self, datagram, rx_port):
    '''Deliver a datagram locally to the "control plane" of the router.'''
    if service := self._services_by_sas.get(datagram.destination_socket): service.inbound(datagram, rx_port)
  
  def start(self):
    '''Start this router.'''
    # Ports are responsible for adding their seed entries to routing_table
    for port in self.ports: port.start(self)
    for _, service in self.services: service.start(self)
  
  def stop(self):
    '''Stop this router.'''
    for _, service in self.services: service.stop()
    for port in self.ports: port.stop()
  
  def inbound(self, datagram, rx_port):
    '''Called by a Port when a Datagram comes in from that port.  The Datagram may be routed, delivered, both, or neither.'''
    
    # a network number of zero means "this network", but we know what that is from the port, so sub it in
    # note that short-header Datagrams always have a network number of zero
    if rx_port.network:
      if datagram.destination_network == datagram.source_network == 0x0000:
        datagram = datagram.copy(destination_network=rx_port.network, source_network=rx_port.network)
      elif datagram.destination_network == 0x0000:
        datagram = datagram.copy(destination_network=rx_port.network)
      elif datagram.source_network == 0x0000:
        datagram = datagram.copy(source_network=rx_port.network)
    
    # if this Datagram's destination network is this port's network, there is no need to route it
    if datagram.destination_network in (0x0000, rx_port.network):
      # if Datagram is bound for the router via the any-router address, the broadcast address, or its own node address, deliver it
      if datagram.destination_node in (0x00, rx_port.node, 0xFF):
        self._deliver(datagram, rx_port)
      return
    
    # if this Datagram's destination network is one the router is connected to, we may need to deliver it
    entry, _ = self.routing_table.get_by_network(datagram.destination_network)
    if entry is not None and entry.distance == 0:
      # if this Datagram is addressed to this router's address on another port, deliver and do not route
      if datagram.destination_network == entry.port.network and datagram.destination_node == entry.port.node:
        self._deliver(datagram, rx_port)
        return
      # if this Datagram is bound for any router on a network to which this router is directly connected, deliver and do not route
      elif datagram.destination_node == 0x00:
        self._deliver(datagram, rx_port)
        return
      # if this Datagram is broadcast to this router's address on another port, deliver but also route
      elif datagram.destination_node == 0xFF:
        self._deliver(datagram, rx_port)
    
    self.route(datagram, originating=False)
  
  def route(self, datagram, originating=True):
    '''Route a Datagram to/toward its destination.'''
    
    if originating:
      if datagram.hop_count != 0: raise ValueError('originated datagrams must have hop count of 0')
      if datagram.destination_network == 0x0000: raise ValueError('originated datagrams must have nonzero destination network')
      # we expect source_network will be zero and we'll fill it in once we know what port we're coming from
    
    # if we still don't know where we're going, we obviously can't get there; discard the Datagram
    if datagram.destination_network == 0x0000: return
    
    entry, _ = self.routing_table.get_by_network(datagram.destination_network)
    
    # you can't get there from here; discard the Datagram
    if entry is None: return
    
    # if we're originating this datagram, we expect that its source network and node will be blank
    if originating:
      # if for some reason the port is in the routing table but doesn't yet have a network and node, discard the Datagram
      if entry.port.network == 0x0000 or entry.port.node == 0x00: return
      # else, fill in its source network and node with those of the port it's coming from
      datagram = datagram.copy(source_network=entry.port.network, source_node=entry.port.node)
    
    # if here isn't there but we know how to get there
    if entry.distance != 0:
      # if the hop count is too high, discard the Datagram
      if datagram.hop_count >= 15: return
      # else, increment the hop count and send the Datagram to the next router
      entry.port.send(entry.next_network, entry.next_node, datagram.hop())
      return
    # special 'any router' address (see IA page 4-7), control plane's responsibility; discard the Datagram
    elif datagram.destination_node == 0x00:
      return
    # addressed to another port of this router's, control plane's responsibility; discard the Datagram
    elif datagram.destination_network == entry.port.network and datagram.destination_node == entry.port.node:
      return
    # the destination is connected to us directly; send the Datagram to its final destination
    else:
      entry.port.send(datagram.destination_network, datagram.destination_node, datagram)
      return
  
  def reply(self, datagram, rx_port, ddp_type, data):
    '''Build and send a reply Datagram to the given Datagram coming in over the given Port with the given data.'''
    
    if datagram.source_node in (0x00, 0xFF):
      pass  # invalid as source, don't reply
    elif datagram.source_network:
      self.route(Datagram(hop_count=0,
                          destination_network=datagram.source_network,
                          source_network=0,  # route will fill this in
                          destination_node=datagram.source_node,
                          source_node=0,  # route will fill this in
                          destination_socket=datagram.source_socket,
                          source_socket=datagram.destination_socket,
                          ddp_type=ddp_type,
                          data=data))
    else:
      rx_port.send(0x0000, datagram.source_node, Datagram(hop_count=0,
                                                          destination_network=0x0000,
                                                          source_network=rx_port.network,
                                                          destination_node=datagram.source_node,
                                                          source_node=rx_port.node,
                                                          destination_socket=datagram.source_socket,
                                                          source_socket=datagram.destination_socket,
                                                          ddp_type=ddp_type,
                                                          data=data))
