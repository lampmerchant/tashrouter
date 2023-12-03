'''Constants and functions used by EtherTalk Ports.'''

from ..datagram import ddp_checksum


class EtherTalkPort:
  '''Mixin class containing constants and functions used by EtherTalk Ports.'''
  
  IEEE_802_2_SAP_OTHER = 0xAA
  IEEE_802_2_DATAGRAM_SVC_CTRL = 0x03
  IEEE_802_2_TYPE_1_HEADER = bytes((IEEE_802_2_SAP_OTHER, IEEE_802_2_SAP_OTHER, IEEE_802_2_DATAGRAM_SVC_CTRL))
  SNAP_HEADER_AARP = bytes((0x00, 0x00, 0x00, 0x80, 0xF3))
  SNAP_HEADER_APPLETALK = bytes((0x08, 0x00, 0x07, 0x80, 0x9B))
  
  AARP_ETHERNET = bytes((0x00, 0x01))
  AARP_APPLETALK = bytes((0x80, 0x9B))
  AARP_HW_ADDR_LEN = 6
  AARP_PROTOCOL_ADDR_LEN = 4
  AARP_LENGTHS = bytes((AARP_HW_ADDR_LEN, AARP_PROTOCOL_ADDR_LEN))
  AARP_HEADER = IEEE_802_2_TYPE_1_HEADER + SNAP_HEADER_AARP + AARP_ETHERNET + AARP_APPLETALK + AARP_LENGTHS
  
  AARP_REQUEST = 1
  AARP_RESPONSE = 2
  AARP_PROBE = 3
  
  AARP_PROBE_TIMEOUT = 0.2  # seconds
  AARP_PROBE_RETRIES = 10
  
  APPLETALK_HEADER = IEEE_802_2_TYPE_1_HEADER + SNAP_HEADER_APPLETALK
  
  ELAP_BROADCAST_ADDR = bytes((0x09, 0x00, 0x07, 0xFF, 0xFF, 0xFF))
  ELAP_MULTICAST_ADDRS = [bytes((0x09, 0x00, 0x07, 0x00, 0x00, i)) for i in range(253)]  # 0x00 to 0xFC
  
  @classmethod
  def elap_multicast_addr(cls, zone_name):
    '''Return the ELAP multicast address for the named zone.'''
    return cls.ELAP_MULTICAST_ADDRS[ddp_checksum(zone_name) % len(cls.ELAP_MULTICAST_ADDRS)]
