'''Constants used by LocalTalk Ports.'''


class LocalTalkPort:
  '''Mixin class containing constants used by LocalTalk Ports.'''
  
  ENQ_INTERVAL = 0.25  # seconds
  ENQ_ATTEMPTS = 8
  
  LLAP_ENQ = 0x81
  LLAP_ACK = 0x82
