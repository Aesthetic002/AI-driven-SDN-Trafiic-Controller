Ryu is a **Python application** that acts as the brain of the SDN network. That's it at its core.

---

**What it actually is**

Ryu is a Python framework — you write a Python class, inherit from Ryu's base app, and it handles all the low-level OpenFlow communication for you. Your code just defines: _"when this event happens, do this."_

It runs on your cloud VM as a process. OvS on your laptop connects to it over TCP port 6633 and maintains a persistent connection. That connection stays open the entire time the network is running.

---

**What it does in your project specifically**

Ryu listens for events from OvS. The main ones are:

- **PacketIn** — "I got a packet I don't have a rule for, what do I do?"
- **FlowRemoved** — "a flow rule just expired, FYI"
- **PortStatus** — "a port went up or down"

When a PacketIn arrives, your Ryu code:

1. Reads the raw packet — extracts source IP, destination IP, port, protocol
2. Classifies it — is this a sensor? video? bulk transfer?
3. Pulls live stats from OvS — link utilization, queue depths, etc.
4. Builds the 20-feature state vector
5. Calls Flask API → gets path decision from DQN
6. Sends FlowMod back to OvS — installs the rule
7. Sends PacketOut — releases the buffered packet

---

**A simple way to think about it**

Imagine OvS is a security guard at a door. The guard has a list of approved visitors (flow table). If someone's on the list — let them in directly. If someone's not on the list — the guard calls the manager.

Ryu is the manager.

The guard doesn't think. The guard just calls the manager for unknown visitors, and the manager decides whether to add them to the list and which door to send them through.

---

**What it looks like in actual code**

This is roughly what your Ryu application looks like — it's just a Python file:

python

```python
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import set_ev_cls

class SDNController(app_manager.RyuApp):

    @set_ev_cls(ofp_event.EventOFPPacketIn)
    def packet_in_handler(self, event):
        # A new unknown packet just arrived
        msg = event.msg          # the raw OpenFlow message
        datapath = msg.datapath  # which switch sent this

        # 1. Parse the packet
        # 2. Build state vector
        # 3. Call Flask → get path
        # 4. Install FlowMod
        # 5. Release buffered packet
```

The `@set_ev_cls` decorator is Ryu's way of saying — _"whenever a PacketIn event fires, call this function."_ You never write the TCP socket code, you never parse raw OpenFlow bytes — Ryu handles all of that. You just write the logic.

---

**Why Ryu and not just talk to OvS directly?**

OpenFlow is a binary protocol over TCP. Talking to OvS directly would mean manually constructing binary message frames, handling connection state, parsing raw bytes. Ryu abstracts all of that into Python objects and event handlers. It's essentially the driver that makes OpenFlow usable in normal Python code.