OvS stands for **Open vSwitch**. It is a software program that pretends to be a physical network switch — but runs entirely in software on your laptop.

---

**What a physical switch does first**

A physical network switch is a box with multiple ethernet ports. Devices plug into it. When a packet arrives on one port, the switch reads the destination address and sends it out the correct port to reach that destination. That's it — it's a traffic director for network packets.

---

**OvS does the exact same thing — but in software**

Instead of a physical box with physical ports, OvS creates **virtual ports** on your laptop. Virtual machines, containers, or Mininet virtual hosts plug into these virtual ports. OvS then does exactly what a physical switch does — reads packets, looks up rules, forwards them out the right port.

The reason this matters for your project is that you don't have 5 physical switches and 10 physical IoT devices in a lab. You have one laptop. OvS lets you simulate an entire network of switches and devices on that one machine.

---

**What makes OvS special vs a normal switch**

A normal switch is dumb and fixed. Its forwarding logic is baked into hardware — you can't change how it makes decisions.

OvS is **programmable**. It speaks the **OpenFlow protocol**, which means an external controller (Ryu) can:

- Read its flow table
- Add new rules
- Delete rules
- Query statistics — bytes per port, packets dropped, queue depth

This is the entire foundation of SDN. Without a programmable switch like OvS, Ryu would have nothing to control.

---

**A simple way to think about it**

Imagine a post office sorting room.

A normal sorting room has fixed rules painted on the wall — "all packages from City A go to shelf 3, all packages from City B go to shelf 7." Nobody can change those rules remotely.

OvS is a sorting room where the rules are written on a **whiteboard** (the flow table). Ryu is the manager sitting in another building who can call up and say "erase shelf 3's rule and write a new one — City A packages now go to shelf 5." The sorting staff (OvS) just follow whatever is on the whiteboard without questioning it.

---

**What OvS specifically does in your project**

Your laptop runs OvS and it serves two roles simultaneously:

**Role 1 — Real switch for physical devices**

Your ESP32 sensor connects to your laptop over WiFi. OvS sits at the boundary and handles those real packets. When the sensor sends data, it hits OvS first.

**Role 2 — Virtual switch for Mininet**

Mininet creates virtual hosts on your laptop (simulating more IoT devices). These virtual hosts connect to OvS through virtual ports. OvS treats them exactly the same as real devices — it doesn't know or care whether a port is physical or virtual.

---

**What OvS actually looks like on your machine**

When you run OvS, it creates something called a **bridge** — which is just the name for a virtual switch instance:

bash

```bash
sudo ovs-vsctl add-br sdn-br
```

This creates a virtual switch called `sdn-br`. You can then add ports to it:

bash

```bash
sudo ovs-vsctl add-port sdn-br eth0    # your physical wifi/ethernet
sudo ovs-vsctl add-port sdn-br veth1   # a virtual port for Mininet
```

And you point it at Ryu:

bash

```bash
sudo ovs-vsctl set-controller sdn-br tcp:<VM-IP>:6633
```

From this moment, OvS contacts Ryu over the internet, establishes the OpenFlow connection, and waits for instructions. Every unknown packet triggers a PacketIn to Ryu. Every FlowMod from Ryu updates the flow table.

---

**The stats OvS exposes — why this matters for your AI**

OvS constantly tracks statistics per port and per flow rule:

- How many bytes/packets passed through each port
- How many packets were dropped
- How long each flow rule has been active
- Queue depths on each port

Ryu queries these stats every 2 seconds:

bash

```bash
ovs-ofctl dump-ports sdn-br      # per-port stats
ovs-ofctl dump-flows sdn-br      # per-flow stats
```

These raw numbers are what Ryu uses to build the 20-feature state vector that feeds into your DQN. So OvS isn't just the switch — it's also the **sensor network** that the AI uses to observe the network's health. Without OvS's stats, the DQN would be blind.