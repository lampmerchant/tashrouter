'''Facilities for logging of network traffic for debug and test purposes.'''

from .netlogger import NetLogger


DEFAULT_LOGGER = NetLogger()

log_datagram_inbound = DEFAULT_LOGGER.log_datagram_inbound
log_datagram_unicast = DEFAULT_LOGGER.log_datagram_unicast
log_datagram_broadcast = DEFAULT_LOGGER.log_datagram_broadcast
log_datagram_multicast = DEFAULT_LOGGER.log_datagram_multicast
log_ethernet_frame_inbound = DEFAULT_LOGGER.log_ethernet_frame_inbound
log_ethernet_frame_outbound = DEFAULT_LOGGER.log_ethernet_frame_outbound
log_localtalk_frame_inbound = DEFAULT_LOGGER.log_localtalk_frame_inbound
log_localtalk_frame_outbound = DEFAULT_LOGGER.log_localtalk_frame_outbound
set_log_str_func = DEFAULT_LOGGER.set_log_str_func
