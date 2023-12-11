# TashRouter

An AppleTalk router that supports LToUDP and TashTalk in addition to EtherTalk.

## Status

Early days!  Basically functional but a long way from mature.

## Quick Start

```python
import logging
import time

import tashrouter.netlog
from tashrouter.port.ethertalk.macvtap import MacvtapPort
from tashrouter.port.localtalk.ltoudp import LtoudpPort
from tashrouter.port.localtalk.tashtalk import TashTalkPort
from tashrouter.router.router import Router


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
tashrouter.netlog.set_log_str_func(logging.debug)

router = Router(ports=(
  LtoudpPort(network=1),
  TashTalkPort('/dev/ttyAMA0', network=2),
  MacvtapPort(macvtap_name='macvtap0', network_min=3, network_max=5),
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
