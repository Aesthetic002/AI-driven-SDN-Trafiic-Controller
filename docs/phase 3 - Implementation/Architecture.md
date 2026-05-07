# System Architecture
### Full Component Diagram and Data Flow

---

## Table of Contents

- [[#Overview|Overview]]
- [[#Component Responsibilities|Component Responsibilities]]
- [[#Process Topology|Process Topology]]
- [[#Data Flow — Packet Lifecycle|Data Flow — Packet Lifecycle]]
- [[#Data Flow — Training Loop|Data Flow — Training Loop]]
- [[#Port and IP Reference|Port and IP Reference]]
- [[#Design Decisions|Design Decisions]]

---

## Overview

The system has five running processes at training time:

```
┌─────────────────────────────────────────────────────────────────────┐
│  NATIVE TERMINAL (sudo required)                                    │
│                                                                     │
│  Process 1: python3 -m ryu.cmd.manager ryu_controller.py  (:6633) │
│  Process 2: train.py → Mininet + scenario_runner (blocks)          │
│  Thread  3: Flask API (api/app.py)                         (:5000) │
│  Thread  4: Dashboard HTTP server                          (:8080) │
│  Thread  5: _file_pump (polls /tmp/sdn_runtime_state.json, 1s)     │
└─────────────────────────────────────────────────────────────────────┘
```

Process 1 (Ryu) and the Flask/dashboard threads are long-lived. Process 2 (Mininet+traffic) runs for 4 × phase_secs then exits, after which train.py prints a summary and shuts down.

All components are started by `train.py` — see [[How_To_Run]] for the exact start order.

---

## Component Responsibilities

| Component | File | Owns |
|-----------|------|------|
| **Topology** | `mininet/iot_topology.py` | Virtual switches, hosts, link parameters |
| **Stats Collector** | `collector/stats_collector.py` | 20-float state vector from OvS counters |
| **DQN Agent** | `agent/dqn_agent.py` | Neural net, replay buffer, gradient updates |
| **Ryu Controller** | `controller/ryu_controller.py` | OpenFlow events, FlowMod installation, training loop |
| **Generators** | `traffic/generators.py` | Per-host traffic (sensor / video / elephant / emergency) |
| **Scenario Runner** | `traffic/scenario_runner.py` | 4-phase traffic orchestration |
| **Flask API** | `api/app.py` | REST endpoints, SSE stream, mock + production mode |
| **Shared State** | `api/shared_state.py` | Thread-safe IPC between Ryu and Flask |
| **Dashboard** | `dashboard/index.html` | D3.js live visualisation |
| **Orchestrator** | `train.py` | Starts everything in order |
| **Constants** | `constants.py` | Single source of truth — all teams import from here |

### Who calls whom

```
scenario_runner
    └─► host.popen(generators.py ...)
            └─► UDP/TCP packets ──► OvS switches ──► PacketIn ──► Ryu

Ryu Controller
    ├─► DQNAgent.select_action(state_seq)
    ├─► StatsCollector.get_state()           (every 2 s)
    ├─► DQNAgent.store() + DQNAgent.learn()  (every 2 s)
    ├─► DQNAgent.save() + save_buffer()      (every 2 s)
    ├─► _write_state_file()                  (→ /tmp/sdn_runtime_state.json)
    ├─► api.shared_state.push_*()            (in-process Flask update)
    └─► datapath.send_msg(OFPFlowMod)        (on PacketIn)

Flask API
    ├─► _file_pump: polls sdn_runtime_state.json every 1s
    ├─► /api/stream: SSE push every 2s → Dashboard
    └─► GET /api/* endpoints read from api.shared_state
```

---

## Process Topology

```
                         ┌──────────────────────────────┐
                         │     MININET PROCESS (sudo)   │
                         │                              │
  CLUSTER A              │  ┌──┐    ┌──┐    ┌──┐       │
  h_sensor1 10.0.0.1 ───►│  │S1│──►│S3│───►│S5│       │
  h_sensor2 10.0.0.2 ───►│  │  │   │  │    │  │       │
  h_camera1 10.0.0.3 ───►│  │  │   │  │    │  │h_server1 10.0.0.9
  h_emerg   10.0.0.4 ───►│  └──┘   └──┘    │  │h_server2 10.0.0.10
                         │   │    ╔╗│       └──┘       │
  CLUSTER B              │   │    ╚╝│(cross-link)       │
  h_sensor3 10.0.0.5 ───►│  ┌──┐   │    ┌──┐           │
  h_sensor4 10.0.0.6 ───►│  │S2│   └───►│S4│──────────►│
  h_camera2 10.0.0.7 ───►│  │  │        │  │           │
  h_actuator10.0.0.8 ───►│  └──┘        └──┘           │
                         │                              │
                         └────────────┬─────────────────┘
                                      │ OpenFlow TCP :6633
                         ┌────────────▼─────────────────┐
                         │     RYU CONTROLLER PROCESS   │
                         │                              │
                         │  ┌─────────────────────────┐ │
                         │  │   IoTController          │ │
                         │  │   switch_features_handler│ │
                         │  │   packet_in_handler      │ │
                         │  │   flow_removed_handler   │ │
                         │  │   _stats_loop (greenlet) │ │
                         │  └──────────┬───────────────┘ │
                         │             │                  │
                         │  ┌──────────▼──────┐           │
                         │  │  DQNAgent       │           │
                         │  │  DuelingLSTM    │           │
                         │  │  ReplayBuffer   │           │
                         │  └─────────────────┘           │
                         │                              │
                         │  ┌──────────────────────┐    │
                         │  │  StatsCollector       │    │
                         │  │  (polls via ovs-ofctl)│    │
                         │  └──────────────────────┘    │
                         └──────────────────────────────┘
```

---

## Data Flow — Packet Lifecycle

A new sensor packet from `h_sensor1` (10.0.0.1) to `h_server1` (10.0.0.9):

```
Step 1  h_sensor1 sends UDP datagram (DSCP=34, port 5005)
        → hits S1 flow table
        → no matching rule (first packet) → table-miss triggers

Step 2  S1 sends PacketIn to Ryu
        PacketIn.match = {in_port=1, eth_type=IPv4, ipv4_src=10.0.0.1, ipv4_dst=10.0.0.9}

Step 3  Ryu packet_in_handler:
        → src_ip=10.0.0.1 ∈ CLUSTER_A_IPS → forward flow
        → flow_key = (10.0.0.1, 10.0.0.9) not in flow_table → new flow
        → is_priority = False (not EMERGENCY_IPS, not ACTUATOR_IPS)
        → state_seq = list(state_buffer)  ← 10 recent snapshots

Step 4  DQNAgent.select_action(state_seq)
        → LSTM forward pass → Q-values for 4 actions
        → argmax (or ε-greedy random) → e.g. ACTION_PATH_A

Step 5  Ryu installs FlowMod rules:
        S1: match(ip_src=10.0.0.1, ip_dst=10.0.0.9) → output(port=5)  [→S3]
        S3: match(ip_src=10.0.0.1, ip_dst=10.0.0.9) → output(port=3)  [→S5]
        S5: match(ip_dst=10.0.0.9) → output(port=3)  [→h_server1] ← static, already there
        (return path rules also installed)

Step 6  Ryu sends PacketOut(action=OFPP_TABLE) → first packet forwarded
        All subsequent packets from 10.0.0.1→10.0.0.9 are handled in OvS
        hardware — no more PacketIn events for this flow

Step 7  FLOW_IDLE_TIMEOUT (10 s after last packet):
        OvS sends FlowRemoved to Ryu
        → flow_table.pop((10.0.0.1, 10.0.0.9))
        → agent.store(state_seq, action, reward, next_state_seq, done=True)
```

---

## Data Flow — Training Loop

```
Every STATS_INTERVAL (2 seconds):

  StatsCollector.get_state()
      ovs-ofctl dump-ports s1 → PortStats{port: {rx_bytes, tx_bytes}}
      ovs-ofctl dump-ports s2, s3, s4
      ovs-ofctl dump-flows s3 → FlowStats (flow counts, byte counters)
      ovs-ofctl dump-flows s4
      → compute 20 normalised features
      → return list[float] length 20

  Ryu patches features:
      state[7]  = path_counts[PATH_A] / 20.0
      state[8]  = path_counts[PATH_B] / 20.0
      state[9]  = path_counts[PATH_C] / 20.0
      state[18] = 1.0 if any flow is_priority else 0.0

  state_buffer.append(state)   ← rolling window, maxlen=10

  For each (flow_key, entry) in flow_table:
      reward = compute_reward(entry.state_seq[-1], entry.action, state)
          = 0.4×latency + 0.3×reliability + 0.2×throughput + 0.1×fairness
          × 5.0 if priority_flag
      agent.store(entry.state_seq, entry.action, reward, next_state_seq, done=False)

  loss = agent.learn()
      → sample 64 transitions from ReplayBuffer
      → Double-DQN Bellman update
      → gradient step (Adam, lr=1e-4)
      → clip gradients (max norm 1.0)
      → epsilon *= 0.995
      → every 100 steps: target.load_state_dict(online.state_dict())

  agent.save(model_weights.pth)          ← every stats cycle (every 2s)
  agent.save_buffer(sdn_replay_buffer.pkl) ← every stats cycle
```

---

## Port and IP Reference

**Host IPs**

| Host | IP | Cluster | Switch | Switch Port |
|------|----|---------|--------|------------|
| h_sensor1 | 10.0.0.1 | A | S1 | 1 |
| h_sensor2 | 10.0.0.2 | A | S1 | 2 |
| h_camera1 | 10.0.0.3 | A | S1 | 3 |
| h_emerg | 10.0.0.4 | A | S1 | 4 |
| h_sensor3 | 10.0.0.5 | B | S2 | 1 |
| h_sensor4 | 10.0.0.6 | B | S2 | 2 |
| h_camera2 | 10.0.0.7 | B | S2 | 3 |
| h_actuator | 10.0.0.8 | B | S2 | 4 |
| h_server1 | 10.0.0.9 | — | S5 | 3 |
| h_server2 | 10.0.0.10 | — | S5 | 4 |

**Switch port assignments**

| Switch | Port | Connects to |
|--------|------|------------|
| S1 | 1–4 | h_sensor1, h_sensor2, h_camera1, h_emerg |
| S1 | 5 | S3 (Path A uplink) |
| S1 | 6 | S4 (Path B uplink) |
| S2 | 1–4 | h_sensor3, h_sensor4, h_camera2, h_actuator |
| S2 | 5 | S3 |
| S2 | 6 | S4 |
| S3 | 1 | S1 |
| S3 | 2 | S2 |
| S3 | 3 | S5 (50 Mbps, 2 ms) |
| S3 | 4 | S4 (cross-link, 50 Mbps, 3 ms) |
| S4 | 1 | S1 |
| S4 | 2 | S2 |
| S4 | 3 | S5 (100 Mbps, 5 ms) |
| S4 | 4 | S3 (cross-link) |
| S5 | 1 | S3 |
| S5 | 2 | S4 |
| S5 | 3 | h_server1 (1 Gbps, 1 ms) |
| S5 | 4 | h_server2 (1 Gbps, 1 ms) |

**Service ports**

| Port | Proto | Traffic type | DSCP |
|------|-------|-------------|------|
| 5005 | UDP | Sensor readings | AF41 (34) |
| 5006 | UDP | Video stream | AF31 (26) |
| 5007 | TCP | Elephant / bulk | BE (0) |
| 5008 | UDP | Actuator commands | EF (46) |

---

## Design Decisions

**Why single-process controller + agent?**  
The DQN agent runs inside the Ryu process (not in a separate process). This avoids inter-process communication latency and keeps the action-to-FlowMod path synchronous. The Flask API (future) will query the controller's state via a shared object or REST call.

**Why `failMode=standalone` for OVSController fallback?**  
When Ryu is not running, OvS switches fall back to a built-in learning-switch mode. The S3↔S4 cross-link creates a loop that would cause broadcast storms without STP. `stp=True` is passed to all switches in standalone mode, and the test waits 35 s for STP convergence before `pingAll`.

**Why return path always via S3?**  
Server-to-IoT return traffic is predominantly small ACKs. Routing these on a fixed path (via S3) simplifies the flow table while not meaningfully affecting performance. The DQN only controls the high-volume IoT→server direction.

**Why Double-DQN instead of vanilla DQN?**  
Vanilla DQN systematically overestimates Q-values, leading to unstable training on sparse rewards. Double-DQN separates action selection (online network) from action evaluation (target network), reducing overestimation bias — critical when packet-loss rewards are near zero for most steps.

See also: [[Modules_Reference]] · [[State_And_Reward]] · [[Training_And_Persistence]] · [[API_And_Dashboard]] · [[How_To_Run]] · [[Troubleshooting]]
