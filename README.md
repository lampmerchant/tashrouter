# TashRouter

An AppleTalk router that supports LToUDP and TashTalk.

## Status

Very early days!  Please neither judge nor depend on this code.

## Quick Start

```python
import time

from tashrouter.port.ltoudp import LtoudpPort
from tashrouter.port.tashtalk import TashTalkPort
from tashrouter.router.router import Router
from tashrouter.service.echo import EchoService
from tashrouter.service.name_information import NameInformationService
from tashrouter.service.routing_table_aging import RoutingTableAgingService
from tashrouter.service.rtmp.responding import RtmpRespondingService
from tashrouter.service.rtmp.sending import RtmpSendingService
from tashrouter.service.zip.responding import ZipRespondingService
from tashrouter.service.zip.sending import ZipSendingService


router = Router(ports=(
  LtoudpPort(network=1),
  TashTalkPort('COM5', network=2),
), services=(
  (EchoService.ECHO_SAS, EchoService()),
  (NameInformationService.NBP_SAS, NameInformationService()),
  (None, RoutingTableAgingService()),
  (RtmpRespondingService.RTMP_SAS, RtmpRespondingService()),
  (None, RtmpSendingService()),
  (ZipRespondingService.ZIP_SAS, ZipRespondingService()),
  (None, ZipSendingService()),
), seed_zones={
  b'LToUDP Network': (1,),
  b'TashTalk Network': (2,),
})
print('router away!')
router.start()

try:
  while True: time.sleep(1)
except KeyboardInterrupt:
  router.stop()
```
