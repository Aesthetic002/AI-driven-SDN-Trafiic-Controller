# Routing Protocols in Classical Networking
### How OSPF, BGP, and RIP Build Routing Tables — And Why They Fall Short for IoT

---

## Table of Contents

- [[#1. Intuition|1. Intuition]]
- [[#2. What a Routing Protocol Does|2. What a Routing Protocol Does]]
- [[#3. RIP — The Oldest, Simplest Protocol|3. RIP — The Oldest, Simplest Protocol]]
- [[#4. OSPF — The Workhorse of Enterprise Networks|4. OSPF — The Workhorse of Enterprise Networks]]
- [[#5. BGP — The Protocol That Runs the Internet|5. BGP — The Protocol That Runs the Internet]]
- [[#6. How Routing Tables Are Built and Used|6. How Routing Tables Are Built and Used]]
- [[#7. The Fundamental Limitations for Our Use Case|7. The Fundamental Limitations for Our Use Case]]
- [[#8. What SDN Replaced and Why|8. What SDN Replaced and Why]]
- [[#9. Role in Our Project|9. Role in Our Project]]
- [[#10. Interconnections|10. Interconnections]]
- [[#11. References for Further Study|11. References for Further Study]]

---

## 1. Intuition

Imagine you're running a postal service and you need to decide which roads to send each mail truck down to reach any destination in the country. You have no GPS, no real-time traffic information. You have only one tool: **maps that your truck drivers share with each other by radio**.

That's classical routing protocols. Every router is a truck driver who:
1. Tells its neighbors which destinations it knows how to reach
2. Listens to what its neighbors say they can reach
3. Builds its own map of the whole road network by assembling all these neighbor reports
4. Chooses the shortest route based on that map

The entire process is **distributed, autonomous, and blind to actual traffic**. Every truck takes its route based on the map — not based on whether that road is currently jam-packed or empty.

This is why classical routing fails for AI-driven IoT: the map-based routing system has no mechanism to say "Road A is congested right now — take Road B." It only knows distances, not conditions.

---

## 2. What a Routing Protocol Does

A routing protocol has three jobs:

**1. Neighbor Discovery**
Routers find each other by sending periodic "Hello" messages on each interface. If a neighbor stops responding, the link is assumed down.

**2. Route Advertisement**
Routers tell their neighbors which IP networks they can reach, and at what cost. This information propagates through the network until every router knows every reachable prefix.

**3. Path Selection**
When multiple paths exist to the same destination, the routing protocol selects the best one based on a metric (hop count, bandwidth, delay) and installs it in the routing table.

All three jobs run continuously, adapting to topology changes (link failures, new links, new routers).

---

## 3. RIP — The Oldest, Simplest Protocol

**RIP (Routing Information Protocol)** is the grandfather of routing protocols. It is rarely used in production today but is important to understand conceptually.

### How RIP Works

- **Metric:** Hop count (number of routers traversed). Maximum 15 hops. A route with 16 hops is considered unreachable.
- **Advertisement:** Every 30 seconds, each router broadcasts its **entire routing table** to all neighbors.
- **Algorithm:** Bellman-Ford (distributed shortest path). Each router picks the path to each destination with the fewest hops.

```
Router A's routing table after RIP:
Destination    Hops    Via
10.0.0.0/24    1       eth1 (directly connected)
10.0.1.0/24    2       eth0 → Router B
10.0.2.0/24    3       eth0 → Router B → Router C
```

### RIP's Problems

| Problem | Effect |
|---|---|
| Hop count metric only | Ignores bandwidth: a 10Gbps link and a 56kbps link are equally "1 hop" |
| Slow convergence | After a failure, it takes 3–6 minutes for the network to stabilize (count-to-infinity problem) |
| Broadcasts full table | Wastes bandwidth; doesn't scale beyond ~50 routers |
| No traffic awareness | Routes based on hops, never on actual link load |

**Relevance to our project:** RIP represents the most extreme failure mode of classical routing. In our 3-switch topology, RIP would see Paths A and B as equivalent (both 2 hops) and always pick one — with no ability to differentiate based on congestion.

---

## 4. OSPF — The Workhorse of Enterprise Networks

**OSPF (Open Shortest Path First)** is the dominant interior routing protocol in enterprise and service provider networks. It is dramatically more sophisticated than RIP.

### How OSPF Works

**Step 1 — Neighbor Adjacency**

OSPF routers send **Hello packets** every 10 seconds on each interface. Two routers that receive each other's Hellos become **neighbors**. After exchanging database descriptions, they become **adjacent** — fully synchronized.

**Step 2 — Link State Advertisement (LSA) Flooding**

Each router describes itself and its links in a structured message called an **LSA (Link State Advertisement)**:

```
LSA from Router A:
    Router ID: 1.1.1.1
    Links:
        - 10.0.0.0/30  (cost=10, to Router B)
        - 10.0.1.0/30  (cost=20, to Router C)
        - 192.168.1.0/24  (directly connected hosts)
```

LSAs are flooded to all routers in the OSPF area. Every router stores all received LSAs in its **Link State Database (LSDB)**.

**Step 3 — SPF Calculation (Dijkstra)**

With the complete LSDB, every router independently runs Dijkstra's algorithm on the full topology graph. The result is the same on every router (since they all have the same LSDB) — a shortest path tree rooted at that router.

```
Router A runs Dijkstra:
    LSDB topology:  A—(10)—B—(5)—C, A—(20)—C
    Shortest paths from A:
        To B: A→B (cost 10) ← via eth1
        To C: A→B→C (cost 15) ← via eth1
              A→C  (cost 20) ← via eth2
    Installed: A→C via eth1 (cost 15 < 20)
```

**Step 4 — Routing Table Update**

The SPF result is written to the routing table (RIB). The data plane's FIB is updated from the RIB via the route manager process.

### OSPF Metric: Cost

OSPF's default metric is **cost**, calculated as:
```
cost = reference_bandwidth / interface_bandwidth
     = 100 Mbps / interface_bandwidth
```

So a 100 Mbps interface has cost 1, a 10 Mbps interface has cost 10, a 1 Mbps interface has cost 100. Unlike RIP, faster links are preferred over slower ones.

**Critical limitation:** Cost is still a **static** property of the interface — it is configured once and does not reflect actual link utilization. A link at 99% utilization has the same cost as the same link at 1% utilization.

### OSPF Convergence

When a link fails:
1. Adjacent routers detect the failure (Hello timeout: ~40 seconds, or fast hello: ~1 second)
2. They generate new LSAs describing the failure
3. LSAs are flooded throughout the area (~seconds)
4. All routers re-run Dijkstra (~milliseconds)
5. Routing tables are updated

**Convergence time:** With fast OSPF timers: 1–3 seconds. Standard timers: 30–90 seconds. During convergence, traffic may be blackholed or looping.

---

## 5. BGP — The Protocol That Runs the Internet

**BGP (Border Gateway Protocol)** is the inter-domain routing protocol — the protocol that glues the thousands of independent networks (Autonomous Systems) of the internet together.

### How BGP Works

BGP is a **path-vector** protocol. Instead of just advertising a destination and its metric, each BGP router advertises the **complete AS path** to a destination:

```
BGP route advertisement from ISP-A to ISP-B:
    Prefix: 203.0.113.0/24
    AS Path: [AS65001, AS65003, AS65007]
    Next Hop: 198.51.100.1
    Local Pref: 100
    MED: 50
```

**Path selection:** BGP has 13+ attributes used in a specific order to select the best path. Policies can be applied at each AS to prefer certain paths, reject others, or modify attributes — enabling traffic engineering at the internet scale.

### Why BGP Is Irrelevant to Our Project

BGP operates between Autonomous Systems (large networks like ISPs). Our project operates within a single small network of 3 virtual switches. BGP is mentioned here for completeness and to contrast with OSPF.

The key point: even BGP — the most sophisticated classical routing protocol — cannot react to real-time link congestion within a link (it reacts to path failures, not gradual congestion) and cannot differentiate IoT traffic types.

---

## 6. How Routing Tables Are Built and Used

The cumulative result of routing protocol operation is the **routing table** — also called the **Forwarding Information Base (FIB)** in its hardware-optimized form.

### Routing Table Structure

```
Destination      Prefix    Protocol   Next Hop        Interface   Metric
10.0.0.10        /32       OSPF       192.168.1.2     eth1        20
10.0.0.11        /32       OSPF       192.168.1.4     eth2        25
10.0.0.0         /24       Connected  —               eth0        0
0.0.0.0          /0        Static     192.168.0.1     eth0        1
```

**Longest prefix match:** When a packet arrives, the router finds the routing table entry with the most specific (longest) matching prefix. A /32 (exact host) match beats a /24 (subnet) match.

**Lookup process:**
```
Packet: dst=10.0.0.10
Lookup: check /32 entries → match found: 10.0.0.10/32 → eth1
Forward out eth1
(Independent of: src IP, src port, dst port, protocol, packet size, link utilization)
```

This is the fundamental limitation for our IoT use case. The routing table sees only the destination. It cannot know:
- Is this packet from a sensor or from a firmware update server?
- Is eth1 currently at 90% utilization?
- Has eth1 been rising in utilization for the last 20 seconds?
- Is this an emergency medical alert?

---

## 7. The Fundamental Limitations for Our Use Case

Classical routing protocols fail our IoT AI-routing project in four specific ways:

### Limitation 1: Load-Blind Routing

OSPF computes shortest paths based on static costs. If both paths to the server have the same cost (which they do in our symmetric topology — both 2 hops), OSPF picks one arbitrarily and sends everything down it.

There is no mechanism in OSPF to say "the cost of this link should be higher right now because it is 85% utilized." OSPF-TE (traffic engineering extensions) adds this capability — but requires manual LSA injection and does not adapt automatically.

### Limitation 2: Traffic Discrimination is Impossible

A routing table entry forwards **all packets** to a destination the same way. A sensor packet and an elephant-flow packet destined for the same IP address take the same path — always.

SDN's flow tables can match on 12+ header fields simultaneously. A sensor packet (UDP:5005) and an elephant flow (TCP:5007) to the same destination IP can be given completely different forwarding rules.

### Limitation 3: No Temporal Awareness

OSPF has no concept of a trend. It cannot notice that link utilization has been rising for 20 seconds and predict imminent congestion. It responds only to failures (a link going completely down), not to gradual degradation.

Our AI's [[LSTM_Memory|LSTM]] is specifically designed to detect such temporal patterns — something fundamentally impossible within a routing protocol framework.

### Limitation 4: Cannot Host AI

Routing protocols are implemented in router firmware written in C/C++. They are closed, vendor-specific, and not extensible. You cannot call `torch.nn.Module.forward()` from inside an OSPF SPF calculation.

SDN moves the routing logic into a Python program (Ryu) where calling any Python ML library is trivial.

---

## 8. What SDN Replaced and Why

In our lab topology, if we had used classical networking instead of SDN:

| Scenario | Classical Result | AI-SDN Result |
|---|---|---|
| Both paths free | OSPF routes all to Path A (lower OSPF ID tiebreak) | AI routes to Path A (optimal anyway) |
| Path A: 90% utilized | OSPF continues routing to Path A (ignores utilization) | AI detects congestion, shifts to Path B |
| Elephant flow on Path A | Sensors queue behind elephant — 200ms latency | AI moves sensors to Path B — <20ms |
| Emergency sensor arrives | Treated identically to firmware update | 5× priority multiplier → best available path |
| Elephant flow ends | OSPF continues routing to Path A (already was) | AI detects Path A clearing, shifts back gradually |

The table shows SDN is only significantly better in the last 4 rows — under congestion or with heterogeneous traffic. Classical routing is perfectly adequate for the uniform low-load scenario. **This is exactly what our experiments are designed to demonstrate.**

---

## 9. Role in Our Project

Classical routing protocols appear in our project as the **baseline to be beaten**. Specifically:

- **Shortest Path routing policy** in our code is not literally running OSPF — it is a simplified Python implementation of Dijkstra that mimics OSPF's behavior. It represents "what classical networking would do."
- **ECMP routing policy** mimics what a modern classical router with equal-cost multipath would do.
- **AI routing policy** is what SDN uniquely enables.

The 9-experiment comparison (3 policies × 3 traffic scenarios) is fundamentally a proof that AI-SDN outperforms what classical networking could ever achieve — because classical networking cannot be traffic-aware, temporally-aware, or learn from experience.

---

## 10. Interconnections

- [[CN_vs_SDN]] — the master comparison document this file feeds into
- [[Control_Plane_vs_Data_Plane]] — routing protocols live entirely in the control plane; this file shows what that control plane does in classical networks
- [[Flow_Tables_SDN]] — the SDN replacement for the routing table; compare directly with this file
- [[Centralized_vs_Distributed_Control]] — routing protocols are the mechanism by which classical distributed control works
- [[Network_Programmability]] — why routing protocol firmware cannot be replaced with AI
- [[Routing_Policies]] *(in Knowledge_System/)* — shows the three policies we compare; Shortest Path mimics OSPF

---

## 11. References for Further Study

- **OSPF RFC 2328** — "OSPF Version 2" — the definitive specification
- **BGP RFC 4271** — "A Border Gateway Protocol 4 (BGP-4)"
- **OSPF-TE RFC 3630** — "Traffic Engineering (TE) Extensions to OSPF Version 2" — closest CN approach to load-aware routing
- **RIP RFC 2453** — "RIP Version 2"
- **Tanenbaum & Wetherall, "Computer Networks"** — Chapter 5 (Network Layer) — comprehensive treatment of all routing algorithms
- **Topics to explore:** IS-IS (alternative to OSPF, used heavily by ISPs), MPLS Traffic Engineering (LDP + RSVP-TE for path control in CN), Segment Routing (SR-MPLS) as a more SDN-like approach to path programming without a full SDN controller
