# TashRouter

An AppleTalk router that supports LToUDP and TashTalk.

## Status

Very early days!  Please neither judge nor depend on this code.

## Quick Start

```
import time

from tashrouter.port.ltoudp import LtoudpPort
from tashrouter.port.tashtalk import TashTalkPort
from tashrouter.router.router import Router
from tashrouter.service.echo import EchoService
from tashrouter.service.rtmp.responding import RtmpRespondingService
from tashrouter.service.rtmp.sending import RtmpSendingService
from tashrouter.service.name_information import NameInformationService
from tashrouter.service.zone_information import ZoneInformationService


router = Router(ports=(
  TashTalkPort('COM5', network=1),
  LtoudpPort(network=2),
), services=(
  (EchoService.ECHO_SAS, EchoService()),
  (RtmpRespondingService.RTMP_SAS, RtmpRespondingService()),
  (None, RtmpSendingService()),
  (NameInformationService.NBP_SAS, NameInformationService()),
  (ZoneInformationService.ZIP_SAS, ZoneInformationService()),
), seed_zones={
  b'TashTalk Network': (1,),
  b'LToUDP Network': (2,),
})
print('router away!')
router.start()

try:
  while True: time.sleep(1)
except KeyboardInterrupt:
  router.stop()
```
