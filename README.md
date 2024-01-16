# TashRouter

An AppleTalk router that supports LocalTalk (via [LToUDP](https://windswept.home.blog/2019/12/10/localtalk-over-udp/) and/or [TashTalk](https://github.com/lampmerchant/tashtalk)) in addition to EtherTalk.

## Status

Not mature yet, but ready for some real world experience.

## Quick Start

### MACVTAP

A MACVTAP device is necessary to support EtherTalk.  Not all kernels may have support for this built in; Void Linux for
Raspberry Pi is known to have support for MACVTAP.

```
# ip link add link eth0 name macvtap0 type macvtap
# ip link set dev macvtap0 promisc on
```

### Running TashRouter

Put something like this into `test_router.py` at the same level as the `tashrouter` directory and run it:

```python
import logging
import time

from tashrouter.netlog import set_log_str_func
from tashrouter.port.ethertalk.macvtap import MacvtapPort
from tashrouter.port.localtalk.ltoudp import LtoudpPort
from tashrouter.port.localtalk.tashtalk import TashTalkPort
from tashrouter.router.router import Router


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
set_log_str_func(logging.debug)  # comment this line for speed and reduced spam

router = Router('router', ports=(
  LtoudpPort(seed_network=1, seed_zone_name=b'LToUDP Network'),
  TashTalkPort(serial_port='/dev/ttyAMA0', seed_network=2, seed_zone_name=b'TashTalk Network'),
  MacvtapPort(macvtap_name='macvtap0', seed_network_min=3, seed_network_max=5, seed_zone_names=[b'EtherTalk Network']),
))

print('router away!')
router.start()
try:
  while True: time.sleep(1)
except KeyboardInterrupt:
  router.stop()
```
