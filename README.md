# TashRouter

An AppleTalk router that supports LToUDP and TashTalk in addition to EtherTalk.

## Status

Early days!  Basically functional but a long way from mature.

## Quick Start

```python
import logging
import time

from tashrouter.port.ethertalk.macvtap import MacvtapPort
from tashrouter.port.localtalk.ltoudp import LtoudpPort
from tashrouter.port.localtalk.tashtalk import TashTalkPort
from tashrouter.router.router import Router
from tashrouter.service.echo import EchoService
from tashrouter.service.name_information import NameInformationService
from tashrouter.service.routing_table_aging import RoutingTableAgingService
from tashrouter.service.rtmp.responding import RtmpRespondingService
from tashrouter.service.rtmp.sending import RtmpSendingService
from tashrouter.service.zip.responding import ZipRespondingService
from tashrouter.service.zip.sending import ZipSendingService


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(module)s %(levelname)s: %(message)s')

router = Router(ports=(
  LtoudpPort(network=1),
  TashTalkPort('/dev/ttyAMA0', network=2),
  MacvtapPort(macvtap_name='macvtap0', network_min=3, network_max=5),
), services=(
  (EchoService.ECHO_SAS, EchoService()),
  (NameInformationService.NBP_SAS, NameInformationService()),
  (None, RoutingTableAgingService()),
  (RtmpRespondingService.RTMP_SAS, RtmpRespondingService()),
  (None, RtmpSendingService()),
  (ZipRespondingService.ZIP_SAS, ZipRespondingService()),
  (None, ZipSendingService()),
), seed_zones=(
  (b'LToUDP Network', 1, 1),
  (b'TashTalk Network', 2, 2),
  (b'EtherTalk Network', 3, 5),
))
print('router away!')
router.start()

try:
  while True: time.sleep(1)
except KeyboardInterrupt:
  router.stop()
```
