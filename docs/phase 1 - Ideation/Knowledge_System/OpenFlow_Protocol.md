# OpenFlow Protocol
### The Language the Controller Uses to Command Switches

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

Imagine a restaurant where the waiters (switches) have no idea how to take orders — they've never seen a menu. Instead, there's a head chef (controller) who knows the full menu and all recipes. The chef radios orders to each waiter via a walkie-talkie using a specific vocabulary of commands:

- **PacketIn:** "Waiter 1, I got a customer who ordered something I don't have on my list. What should I do?"
- **FlowMod:** "Waiter 2, from now on: whenever a customer at Table 5 orders salmon, take it to kitchen station 3."
- **PacketOut:** "Waiter 1, take this specific dish and bring it to Table 8 right now."
- **StatsRequest/Reply:** "Waiter 3, how many dishes have you served this hour? How full are your trays?"

**OpenFlow is that walkie-talkie language.** It's a standardized protocol that lets the [[SDN_Controller|SDN controller]] program any OpenFlow-compatible switch — regardless of vendor — using a common set of messages.

---

## 2. Technical Explanation

### The Control Plane vs Data Plane Separation

OpenFlow enables the fundamental SDN architecture principle:

| Concept | Traditional Network | OpenFlow SDN |
|---|---|---|
| **Control Plane** | Runs in every switch brain | Centralized in the controller |
| **Data Plane** | Executes decisions locally | Executes instructions from controller |
| **Intelligence** | Distributed, independent | Centralized, coordinated |
| **Programmability** | Requires vendor-specific tools | Standardized, any controller |

OpenFlow is the **southbound protocol** — it lives between the controller (north, intelligence) and the switches (south, data forwarders).

### The Flow Table

The core data structure of every OpenFlow switch is the **flow table** — a set of rules. Each rule has three parts:

```
╔════════════════════╦═══════════════════════╦════════════════════════╗
║ MATCH FIELDS       ║ ACTIONS               ║ COUNTERS               ║
╠════════════════════╬═══════════════════════╬════════════════════════╣
║ in_port=1          ║ output(port=3)        ║ packets=1,247          ║
║ eth_type=IPv4      ║                       ║ bytes=187,050          ║
║ ip_dst=10.0.0.10   ║                       ║ duration=42s           ║
║ ip_proto=UDP       ║                       ║                        ║
║ udp_dst=5005       ║                       ║                        ║
╠════════════════════╬═══════════════════════╬════════════════════════╣
║ eth_type=IPv4      ║ output(port=2)        ║ packets=48             ║
║ ip_dst=10.0.0.11   ║                       ║ bytes=84KB             ║
║ tcp_dst=5007       ║                       ║                        ║
╠════════════════════╬═══════════════════════╬════════════════════════╣
║ (table-miss rule)  ║ output(CONTROLLER)    ║ packets=12             ║
║                    ║                       ║                        ║
╚════════════════════╩═══════════════════════╩════════════════════════╝
```

Packets are matched **top-to-bottom, highest priority first.** The first matching rule wins. If no rule matches, the table-miss rule triggers — in our case, sending the packet to the controller.

### The Four Key Message Types

#### 1. PacketIn (Switch → Controller)

Sent when a packet arrives at the switch and **no matching flow rule exists** (table-miss).

```
PacketIn message contains:
    - datapath_id: which switch sent this
    - in_port: which port the packet arrived on
    - data: the full packet payload (so controller can inspect it)
    - reason: TABLE_MISS or ACTION (explicit SEND_TO_CONTROLLER action)
```

In Ryu Python:
```python
@set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
def packet_in_handler(self, ev):
    msg = ev.msg
    datapath = msg.datapath        # The OvS switch object
    in_port = msg.match['in_port']
    pkt = packet.Packet(msg.data)  # Parse the raw packet bytes
    # Extract IP, UDP/TCP headers...
    # Classify flow type, query AI agent, install FlowMod
```

#### 2. FlowMod (Controller → Switch)

The most important message. Installs, modifies, or deletes a rule in the flow table.

```
FlowMod contains:
    - command: OFPFC_ADD (add new rule), OFPFC_MODIFY, OFPFC_DELETE
    - match: conditions that must be satisfied (dst_ip, protocol, port, etc.)
    - actions: what to do when matched (output port, drop, modify headers)
    - priority: higher priority rules are checked first (0–65535)
    - idle_timeout: seconds before rule expires if no matching packet arrives
    - hard_timeout: hard deadline regardless of traffic (0 = never)
    - buffer_id: if set, also forward the buffered first packet
```

In Ryu:
```python
def add_flow(self, datapath, priority, match, actions, idle_timeout=30, hard_timeout=120):
    ofproto = datapath.ofproto
    parser = datapath.ofproto_parser

    inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
    mod = parser.OFPFlowMod(
        datapath=datapath,
        priority=priority,
        match=match,
        instructions=inst,
        idle_timeout=idle_timeout,
        hard_timeout=hard_timeout
    )
    datapath.send_msg(mod)
```

#### 3. PacketOut (Controller → Switch)

Used to send a specific packet immediately out of a specific port, without going through the flow table. Used to forward the very first packet of a new flow while simultaneously installing the FlowMod for all subsequent packets.

```python
out = parser.OFPPacketOut(
    datapath=datapath,
    buffer_id=msg.buffer_id,
    in_port=in_port,
    actions=[parser.OFPActionOutput(out_port)],
    data=msg.data
)
datapath.send_msg(out)
```

#### 4. StatsRequest / StatsReply (Controller ↔ Switch)

The controller periodically polls switches for statistics. We use this to build the state vector for the AI.

```python
# Request port statistics from all switches
req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
datapath.send_msg(req)

# Reply handler
@set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
def port_stats_reply_handler(self, ev):
    for stat in ev.msg.body:
        port_no = stat.port_no
        rx_bytes = stat.rx_bytes
        tx_bytes = stat.tx_bytes
        # Compute utilization = delta_bytes / (poll_interval × link_capacity)
```

---

## 3. Mathematical / Algorithmic Details

### Flow Rule Matching Priority

When a packet arrives at an OvS switch, the match logic is:

```
For each rule in flow_table, sorted by priority (descending):
    if packet_matches(rule.match_fields):
        execute(rule.actions)
        update(rule.counters)
        return    ← stop, first match wins
Table-miss: send to controller
```

Match fields support wildcards — a rule matching only `ip_dst=10.0.0.10` matches all packets to that IP regardless of source, protocol, or port.

### Timeout Mechanics

| Timeout Type | Behavior | Our Use Case |
|---|---|---|
| `idle_timeout=30` | Rule expires if no packet matches for 30s | Sensor rules expire between 5s readings → new PacketIn → fresh AI decision |
| `hard_timeout=120` | Rule expires unconditionally after 120s | Forces re-evaluation of elephant flow routing |
| `hard_timeout=0` | Rule never expires | Permanent infrastructure rules (ARP, LLDP) |

Timeouts are our mechanism for **forcing the AI to re-evaluate routing** as network conditions change. If a sensor flow has a 30-second idle timeout, the AI gets to make a new routing decision every 30 seconds even if the sensor sends data continuously.

### Utilization Calculation from StatsReply

```
poll_delta_bytes = current_tx_bytes - previous_tx_bytes
time_delta = current_poll_time - previous_poll_time
bytes_per_sec = poll_delta_bytes / time_delta
utilization = bytes_per_sec / link_capacity_bytes_per_sec
```

Polled every 2 seconds → fresh state vector every 2s.

---

## 4. Role in Our Project

OpenFlow is the **execution layer** — it's how the AI's routing decisions become reality in the actual network.

**The exact sequence in our system:**

1. A new IoT device packet arrives → OvS switches look up flow table → miss → PacketIn to Ryu
2. Ryu calls the Flask API → AI agent selects the best path → returns port number
3. Ryu sends a FlowMod to OvS → installs the rule (match this flow → output to port N)
4. Ryu sends a PacketOut → the first packet is forwarded immediately
5. All subsequent packets are handled by OvS at hardware speed — no controller bottleneck
6. Ryu polls SwitchStats every 2 seconds → extracts bytes/sec per port → computes the [[State_Space|20-feature state vector]]
7. When the AI agent submits the reward (after flow completion), Ryu uses flow statistics from the FlowStatsReply to compute bytes delivered, duration, and packet loss

Without OpenFlow, the AI's decisions would have no path to the physical network. OpenFlow is what transforms an abstract "choose Path B" into actual packet forwarding in the OvS switch.

---

## 5. Interconnections

- [[SDN_Controller]] — the Ryu controller is the entity that sends and receives OpenFlow messages
- [[Network_Topology]] — the physical links and ports that FlowMod rules reference
- [[DQN_Model]] — the AI's chosen action (path index) is translated into an OpenFlow port number for the FlowMod
- [[State_Space]] — StatsRequest/Reply messages are the source of per-port statistics used to build the state vector
- [[Feature_Engineering]] — raw OvS counter data (rx_bytes, tx_bytes, queue_depth) flows through OpenFlow StatsReply into feature calculation
- [[Training_Process]] — FlowStats data provides feedback (bytes delivered, duration) used in [[Reward_Function|reward computation]]

---

## 6. Advanced Insights

### OpenFlow Versions and Our Choice (1.3)

We use **OpenFlow 1.3** because:
- Introduces **multiple flow tables** (not just one) — more complex matching pipelines
- Supports **meters** (rate limiting) and **groups** (multicast, failover rules)
- Adds MPLS label matching — useful for future traffic engineering
- Ryu's full feature set is optimized for OF 1.3

OpenFlow 1.0 would also work for our two-path routing, but lacks meters and tables that future extensions would need.

### The Controller Bottleneck Problem

Every new flow (first packet) goes through the controller. If the network has 10,000 flows per second all arriving simultaneously, the controller faces a **PacketIn storm**. Our mitigation:

1. **Flow rules with idle timeouts:** ≥5s idle timeout means a flow never hits the controller more than once per 5 seconds
2. **Pre-installed rules:** For known traffic types (sensor on UDP:5005), the controller can pre-install permanent rules after learning the topology — avoiding PacketIn entirely
3. **Switch-local fallback:** If the controller is unreachable, OvS switches fall into **fail-secure mode** (drop all unknown packets) or install a default rule

### Multi-Table Pipelines

OpenFlow 1.3 supports routing packets through multiple flow tables in sequence:

```
Table 0 (classification): match → set metadata (priority_flag, flow_type)
                                 → goto Table 1
Table 1 (routing):        match metadata + dst_ip → output port
```

Our current system uses a single table, but a multi-table design would cleanly separate flow classification from routing decisions — a natural architecture improvement.

---

## 7. References for Further Study

- **OpenFlow 1.3 specification** — Open Networking Foundation (ONF) — the definitive reference
- **Ryu SDN Controller documentation** — ryu.readthedocs.io — Python API for all message types
- **SDN Architecture** — ONF's "Software-Defined Networking: The New Norm for Networks" (2012) — foundational white paper
- **P4 language** — A more expressive alternative to OpenFlow for programmable data planes
- **Topics to explore:** ONOS and OpenDaylight (alternative SDN controllers), P4Runtime (next-gen programmable networking), segment routing (SR-MPLS) as a data plane programming model, gRPC-based southbound interfaces
