# SDN Controller
### Ryu — The Centralized Brain of the Network

---

## Table of Contents

- [[#1. Intuition|1. Intuition]]
- [[#2. Technical Explanation|2. Technical Explanation]]
- [[#3. Mathematical / Algorithmic Details|3. Mathematical / Algorithmic Details]]
- [[#4. Role in Our Project|4. Role in Our Project]]
- [[#5. Interconnections|5. Interconnections]]
- [[#6. Advanced Insights|6. Advanced Insights]]
- [[#7. References for Further Study|7. References for Further Study]]

---

## 1. Intuition

In a traditional network, every switch is its own boss. Each one independently runs a routing protocol (like OSPF or BGP), builds its own routing table, and decides where to send packets — all without coordinating with other switches. This is like a city where every intersection has its own traffic light controller with no connection to the others. Each intersection just does its best locally. The result? Suboptimal traffic flow, no possibility of coordinated rerouting.

**SDN (Software Defined Networking) changes this entirely.**

In an SDN, the intelligence is pulled out of every switch and placed in a single, central program: the **SDN Controller**. The switches themselves become "dumb forwarders" — they just look at a table of rules and follow them. The controller decides what those rules are, and can update them in real time.

Think of it like a city's **traffic control center**: one room with screens showing every intersection, with the ability to change any traffic light remotely, coordinate green waves for emergency vehicles, and redirect traffic away from accidents — all from one place.

**Our controller is Ryu** — a Python-based SDN controller framework. It speaks **[[OpenFlow_Protocol|OpenFlow]]** to the switches, manages the entire network topology, and serves as the bridge between the physical network and our [[DQN_Model|AI routing agent]].

---

## 2. Technical Explanation

### What Ryu Actually Is

Ryu is not just a single program — it's a **framework** for building SDN applications. You write a Python class that inherits from Ryu's base app and registers event handlers. Ryu handles all the low-level OpenFlow socket connections, message parsing, and threading. You just write the logic.

```python
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, udp, tcp

class SDNController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}          # {dpid: datapath object}
        self.topology_graph = nx.DiGraph()
        self.routing_policy = 'ai'   # 'shortest_path', 'ecmp', 'ai'
        self.stats_interval = 2      # Poll switch stats every 2 seconds
        self.path_flows = {}         # Track which flows are on which paths
        # Start background stats polling thread
        hub.spawn(self._stats_polling_loop)
```

### The Three Core Event Handlers

#### Handler 1: Switch Feature Handshake (`EventOFPSwitchFeatures`)

Triggered when a new switch connects to the controller. Used to:
1. Store the switch's datapath object (the handle to communicate with it)
2. Install a **table-miss flow entry** — the rule that sends unknown packets to the controller

```python
@set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
def switch_features_handler(self, ev):
    datapath = ev.msg.datapath
    ofproto  = datapath.ofproto
    parser   = datapath.ofproto_parser

    # Store the datapath for later use
    self.datapaths[datapath.id] = datapath

    # Install table-miss rule: unknown packets → send to controller
    match = parser.OFPMatch()           # Matches EVERYTHING
    actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                      ofproto.OFPCML_NO_BUFFER)]
    self._add_flow(datapath, priority=0, match=match, actions=actions)

    self.logger.info("Switch %s connected", datapath.id)
```

#### Handler 2: PacketIn — New Flow Arrives (`EventOFPPacketIn`)

The most important handler. Triggered every time a packet arrives at a switch with no matching flow rule.

```python
@set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
def packet_in_handler(self, ev):
    msg      = ev.msg
    datapath = msg.datapath
    in_port  = msg.match['in_port']

    # 1. Parse the packet
    pkt     = packet.Packet(msg.data)
    eth_pkt = pkt.get_protocol(ethernet.ethernet)
    ip_pkt  = pkt.get_protocol(ipv4.ipv4)
    udp_pkt = pkt.get_protocol(udp.udp)
    tcp_pkt = pkt.get_protocol(tcp.tcp)

    if ip_pkt is None:
        return   # Ignore non-IP packets (ARP handled separately)

    # 2. Classify the flow type
    flow_type, priority_flag = self._classify_flow(udp_pkt, tcp_pkt, ip_pkt)

    # 3. Build flow_info dict
    flow_info = {
        'src_ip':       ip_pkt.src,
        'dst_ip':       ip_pkt.dst,
        'flow_type':    flow_type,       # 'sensor', 'video', 'elephant', 'unknown'
        'priority':     priority_flag,
        'bytes_so_far': self._get_flow_bytes(ip_pkt.src, ip_pkt.dst),
    }

    # 4. Ask the routing policy for the output port
    out_port = self._get_routing_decision(datapath.id, ip_pkt.dst, flow_info)

    if out_port is None:
        return   # No path available — drop

    # 5. Install the flow rule (FlowMod)
    match = self._build_match(datapath, ip_pkt, udp_pkt, tcp_pkt)
    actions = [datapath.ofproto_parser.OFPActionOutput(out_port)]
    self._add_flow(datapath, priority=10, match=match, actions=actions,
                   idle_timeout=30, hard_timeout=120)

    # 6. Forward the first packet immediately (PacketOut)
    self._send_packet_out(datapath, msg.buffer_id, in_port, out_port, msg.data)

    self.logger.info("Flow %s→%s: type=%s → port %d",
                     ip_pkt.src, ip_pkt.dst, flow_type, out_port)
```

#### Handler 3: Port Statistics Reply (`EventOFPPortStatsReply`)

Handles the response from switch statistics requests — the raw data used to build the [[State_Space|20-feature state vector]].

```python
@set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
def port_stats_reply_handler(self, ev):
    dpid = ev.msg.datapath.id
    now  = time.time()

    for stat in ev.msg.body:
        port = stat.port_no
        key  = (dpid, port)

        prev = self.port_stats_prev.get(key, {'rx': 0, 'tx': 0, 'time': now})
        dt   = now - prev['time']
        if dt <= 0:
            continue

        # Bytes per second on this port
        rx_bps = (stat.rx_bytes - prev['rx']) / dt
        tx_bps = (stat.tx_bytes - prev['tx']) / dt

        # Normalized utilization (0–1)
        utilization = tx_bps / LINK_CAPACITY_BPS

        self.port_stats[key] = {
            'utilization': min(utilization, 1.0),
            'rx_bps': rx_bps,
            'tx_bps': tx_bps,
            'rx_packets': stat.rx_packets,
            'tx_packets': stat.tx_packets,
            'rx_dropped': stat.rx_dropped,
            'tx_dropped': stat.tx_dropped,
        }

        # Update for next delta calculation
        self.port_stats_prev[key] = {
            'rx': stat.rx_bytes, 'tx': stat.tx_bytes, 'time': now
        }
```

### The Routing Decision Function

This is where the controller connects to the AI agent:

```python
def _get_routing_decision(self, dpid, dst_ip, flow_info):
    if self.routing_policy == 'shortest_path':
        path = self.sp_router.get_path(dpid, self._ip_to_dpid(dst_ip), flow_info)

    elif self.routing_policy == 'ecmp':
        path = self.ecmp_router.get_path(dpid, self._ip_to_dpid(dst_ip), flow_info)

    elif self.routing_policy == 'ai':
        # Query the AI agent via Flask REST API
        state_seq = self.state_collector.get_state_sequence()  # (10, 20)
        response = requests.post(
            f"{AI_API_URL}/api/routing",
            json={
                'state_sequence': state_seq.tolist(),
                'flow_info': flow_info,
                'dpid': dpid
            },
            timeout=0.5     # 500ms timeout — can't wait longer for routing
        )
        action = response.json()['action']   # 0=PathA, 1=PathB, 2=Drop
        path = self._action_to_path(action, dpid, dst_ip)

    # Convert path (list of DPIDs) to output port on this switch
    if path and len(path) >= 2:
        next_hop = path[path.index(dpid) + 1]
        return self.topology_graph[dpid][next_hop]['port']

    return None   # No path
```

### The Stats Polling Loop

A background thread that polls all connected switches every 2 seconds:

```python
def _stats_polling_loop(self):
    while True:
        hub.sleep(self.stats_interval)
        for dpid, datapath in self.datapaths.items():
            parser   = datapath.ofproto_parser
            ofproto  = datapath.ofproto
            # Request port stats
            req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
            datapath.send_msg(req)
            # Request flow stats (for per-flow byte counts)
            req2 = parser.OFPFlowStatsRequest(datapath)
            datapath.send_msg(req2)
```

### Flow Classification

```python
def _classify_flow(self, udp_pkt, tcp_pkt, ip_pkt):
    """Classify flow type from packet headers."""
    priority_flag = False

    # Check DSCP field for priority marking
    if ip_pkt and (ip_pkt.tos >> 2) == 46:   # DSCP EF (Expedited Forwarding)
        priority_flag = True

    if udp_pkt:
        if udp_pkt.dst_port == 5005:
            return 'sensor', priority_flag
        elif udp_pkt.dst_port == 5006:
            return 'video', priority_flag

    if tcp_pkt:
        if tcp_pkt.dst_port == 5007:
            return 'elephant', priority_flag

    return 'unknown', priority_flag
```

---

## 3. Mathematical / Algorithmic Details

### Topology Discovery with LLDP

Ryu uses **Link Layer Discovery Protocol (LLDP)** to automatically build the network graph. Every few seconds, Ryu sends LLDP packets out of every port on every switch. When a switch receives an LLDP packet on a port, it sends it to Ryu as a PacketIn. Ryu then knows: "Switch B received an LLDP packet from Switch A on port X — so Switch A's port Y connects to Switch B's port X."

This builds a `networkx.DiGraph`:

```
# After topology discovery:
graph.nodes = [1, 2, 3]         # Switch DPIDs
graph.edges = {
    (1, 2): {'port': 2, 'delay': 10, 'bw': 5_000_000},   # S1→S2 (Path A)
    (2, 1): {'port': 1, 'delay': 10, 'bw': 5_000_000},
    (1, 3): {'port': 3, 'delay': 15, 'bw': 5_000_000},   # S1→S3 (Path B)
    (3, 1): {'port': 1, 'delay': 15, 'bw': 5_000_000},
}
```

### Reward Submission — Closing the Learning Loop

After a flow completes (detected via FlowStatsReply showing counter stopped incrementing), the controller computes the reward and submits it to the AI agent:

```python
def _on_flow_complete(self, flow_key, final_stats):
    duration    = final_stats['duration']
    bytes_sent  = final_stats['bytes']
    packets     = final_stats['packets']
    drops       = final_stats['drops']

    loss_rate   = drops / max(packets + drops, 1)
    delay_ms    = self._measure_round_trip(flow_key)
    throughput  = bytes_sent / (duration * LINK_CAPACITY_BYTES)

    reward_payload = {
        'flow_key':    str(flow_key),
        'delay_ms':    delay_ms,
        'loss_rate':   loss_rate,
        'throughput':  throughput,
        'priority':    flow_key.priority_flag,
        'done':        True
    }

    requests.post(f"{AI_API_URL}/api/feedback", json=reward_payload)
```

---

## 4. Role in Our Project

The SDN Controller is the **orchestration layer** — it owns the network and coordinates everything:

| Responsibility | What Ryu Does |
|---|---|
| Switch management | Maintains persistent OpenFlow TCP connections to all switches |
| Topology awareness | Discovers and maintains the network graph via LLDP |
| Packet classification | Parses PacketIn events and identifies flow type and priority |
| Routing policy execution | Calls Shortest Path, ECMP, or AI (via Flask) to get path decision |
| Rule installation | Issues FlowMod messages to program switch flow tables |
| Statistics collection | Polls all switches every 2 seconds for port and flow counters |
| State vector provider | Transforms raw statistics into the [[State_Space|20-feature state vector]] |
| Reward submission | Measures flow outcomes and submits reward to AI REST API |
| Policy hot-switching | Accepts REST requests to switch between routing policies live |

Without the controller, the switches are deaf and dumb — they cannot forward any traffic. Without the controller's statistics, the AI has no state to reason about. Without the controller's FlowMod messages, the AI's decisions never reach the network.

---

## 5. Interconnections

- [[OpenFlow_Protocol]] — the specific messages (PacketIn, FlowMod, StatsRequest) that Ryu sends and receives
- [[DQN_Model]] — the AI agent that Ryu consults for routing decisions via the Flask REST API
- [[Network_Topology]] — the physical graph that Ryu discovers via LLDP and stores as a NetworkX DiGraph
- [[Routing_Policies]] — the three routing policies (Shortest Path, ECMP, AI) that Ryu can switch between
- [[Feature_Engineering]] — Ryu's statistics collection is the raw data pipeline for building the state vector
- [[State_Space]] — Ryu computes the 20 features from its collected statistics and flow tracking data
- [[Reward_Function]] — Ryu measures flow outcomes (delay, loss, throughput) and submits them to the AI for reward calculation
- [[IoT_Traffic_Types]] — Ryu classifies each new flow into sensor/video/elephant based on port numbers and DSCP markings

---

## 6. Advanced Insights

### The 500ms Problem

When the controller queries the AI agent, it has a 500ms timeout. During this 500ms, the very first packet of the flow is buffered at the switch. If the AI (Flask + PyTorch forward pass) takes longer than 500ms, the controller times out and falls back to a default rule (usually: drop or use ECMP).

In practice, the LSTM forward pass for a `(1, 10, 20)` input takes ~5–8ms on CPU. The Flask HTTP round-trip adds ~2–5ms on a local network. Total: ~10–15ms — well within the 500ms budget.

On a heavily loaded VM (e.g., training simultaneously with inference), this could slip to 50–100ms. Always evaluate AI API latency before deployment.

### Fail-Open vs Fail-Secure

When the controller is unreachable (network partition, controller crash), OvS switches enter either:
- **Fail-open:** Continue forwarding based on existing flow table rules, flood unknown packets
- **Fail-secure:** Drop all packets that don't have an existing rule

We configure fail-secure for safety in our IoT context — it's better to drop sensor readings than to forward emergency alerts to the wrong destination. Existing flows continue on their installed rules; only new flows are blocked until controller reconnects.

```bash
sudo ovs-vsctl set-fail-mode sdn-br secure
```

### Controller Scalability

Ryu is single-threaded by default (uses Python's `eventlet` cooperative scheduling). For our small topology (3 switches, ~10 flows), this is fine. For production networks with thousands of switches:

- Use **ONOS** or **OpenDaylight** — Java-based controllers with proper multithreading
- Deploy **multiple controller instances** with a distributed coordination layer (ZooKeeper)
- Use **controller partitioning** — each controller manages a subset of switches

### The Control Plane / Data Plane Latency Trade-off

Every new flow incurs a PacketIn → controller → FlowMod round trip. In a network with 10,000 new flows per second (large datacenter), this is 10,000 controller interactions per second — a major bottleneck.

Mitigations in our project:
- **Proactive rule installation:** For known traffic types, install rules before the flow starts
- **Wildcard matching:** Install broad rules (e.g., "all UDP from this host → Path B") to reduce the number of PacketIn events
- **Idle timeout tuning:** Keep flow rules alive long enough to avoid re-installation for short-interval periodic flows (sensors send every 5s — idle_timeout should be ≥6s)

---

## 7. References for Further Study

- **Ryu SDN Framework documentation** — ryu.readthedocs.io — authoritative reference for all event handlers and message types
- **OpenDaylight project** — opendaylight.org — enterprise-grade SDN controller alternative
- **ONOS (Open Network Operating System)** — onosproject.org — carrier-grade distributed SDN controller
- **SDN architecture landscape** — ONF TR-521 "SDN Architecture" — formal definition of SDN layers and interfaces
- **Topics to explore:** P4 language for data plane programming (beyond OpenFlow), Intent-based networking (higher-level control abstractions), Controller clustering with RAFT consensus, gRPC southbound interface as a modern alternative to OpenFlow, VPP (Vector Packet Processing) for high-performance software switching
