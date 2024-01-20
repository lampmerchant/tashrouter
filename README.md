# TashRouter

## Introduction

### What is it?

TashRouter is a fully standards-compliant AppleTalk router that supports LocalTalk (via [LToUDP](https://windswept.home.blog/2019/12/10/localtalk-over-udp/) and/or [TashTalk](https://github.com/lampmerchant/tashtalk)) in addition to EtherTalk.

### What can it do?

TashRouter can connect multiple AppleTalk networks of different types and define zones in them.  It can fully replace the functionality of EtherTalk bridge devices (such as AsantéTalk) without resorting to the kinds of standards-breaking hacks that they use.  For example, you could connect an instance of [Mini vMac](https://www.gryphel.com/c/minivmac/index.html) [v37](https://68kmla.org/bb/index.php?threads/emulation-binaries-for-mini-vmac-37-with-ltoudp.46443/) (which can emulate LocalTalk over LToUDP) and a Macintosh 512k (which can connect to a LocalTalk network that TashRouter can access using [TashTalk](https://github.com/lampmerchant/tashtalk)) to a [Netatalk](https://github.com/Netatalk/netatalk) v2.x server to share files and printers.

### What do I need to run it?

A single-board computer such as a Raspberry Pi makes an ideal host for TashRouter.  A [TashTalk Hat](https://ko-fi.com/s/60b561a0e3) will allow a device with a Raspberry Pi-compatible GPIO header to connect to a LocalTalk network.

However, a single-board computer is not required - any computer that can run [Python](https://www.python.org/) v3.x can run TashRouter.  For example, a server running [Void Linux](https://voidlinux.org/) can route between an EtherTalk network and a LocalTalk network running LToUDP, while an [AirTalk](https://airtalk.shop/product/airtalk-complete/) wirelessly bridges the LToUDP network to a physical LocalTalk network.  TashRouter will also run on Windows, but since it currently has no EtherTalk port drivers that support Windows, it is limited to routing between LocalTalk networks via LToUDP and TashTalk.

### Where can I get support?

There is a thread on the [68kMLA forum](https://68kmla.org/bb/index.php?threads/tashrouter-an-appletalk-router.46047/) frequented by the author and other knowledgeable vintage Mac enthusiasts.

## Status

Fully usable, code-complete, and ready for some real-world experience.  Codebase is not yet mature, however - undetected bugs may exist.

## Quick Start - macvtap

### Creating a macvtap device

A macvtap device is necessary to support EtherTalk.  Not all kernels may have support for this built in; [Void Linux](https://voidlinux.org/) for Raspberry Pi is known to have support for macvtap out of the box.  Use the following shell commands (as root) to set up a macvtap device for use with TashRouter:

```
# ip link add link eth0 name macvtap0 type macvtap
# ip link set dev macvtap0 promisc on
```

This process can be automated, though the method of doing so depends on your operating system.  In Void Linux, for example, the above commands can be added to `rc.local`.

### Running TashRouter

Download and unzip the Python v3.x source code for TashRouter.

Put the following into a file called `test_router.py` at the same level as the `tashrouter` directory, optionally customizing parameters such as the serial port for TashTalk, network numbers, and zone names:

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

Run the script you just created: `python3 test_router.py`

## Using TashRouter with a tap and Netatalk 2.x

See [this post](https://68kmla.org/bb/index.php?threads/tashrouter-an-appletalk-router.46047/post-518796) on the 68kMLA forum.
