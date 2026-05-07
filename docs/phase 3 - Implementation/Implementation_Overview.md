# Implementation Overview
### AI-Driven SDN for IoT — Phase 3 Documentation

---

## Table of Contents

- [[#Project Summary|Project Summary]]
- [[#System Architecture|System Architecture]]
- [[#What We Built|What We Built]]
  - [[#Phase 0 — Environment Setup|Phase 0 — Environment Setup]]
  - [[#Phase 1 — Virtual Topology|Phase 1 — Virtual Topology]]
  - [[#Phase 2 — Stats Collector|Phase 2 — Stats Collector]]
  - [[#Phase 3 — DQN Agent|Phase 3 — DQN Agent]]
  - [[#Phase 5 — Ryu SDN Controller|Phase 5 — Ryu SDN Controller]]
  - [[#Phase 6 — Traffic Generators|Phase 6 — Traffic Generators]]
- [[#How It All Works Together|How It All Works Together]]
- [[#Future Work|Future Work]]

---

## Project Summary

This project builds an **AI-controlled Software-Defined Network** for IoT devices. A Dueling LSTM-DQN agent observes live network statistics and decides in real time which path each flow should take through the network. The system must outperform traditional routing (Shortest Path and ECMP) in mixed IoT traffic scenarios.

**Stack:** Mininet · Open vSwitch · Ryu · PyTorch (CPU) · Flask · D3.js  
**Platform:** Single Manjaro laptop — all components run locally, no cloud VM.

The DQN selects from **4 actions** for every new flow:

| Action | Path | Description |
|--------|------|-------------|
| `PATH_A` | S1/S2 → S3 → S5 | Low latency (7 ms end-to-end from Cluster A) |
| `PATH_B` | S1/S2 → S4 → S5 | High bandwidth (100 Mbps server-side link) |
| `PATH_C` | S1/S2 → S3 → S4 → S5 | Cross-link overflow (last resort) |
| `DROP`   | — | Discard low-priority flows under heavy congestion |

---

## System Architecture

See [[Architecture]] for the full component diagram and data-flow walkthrough.

```
┌──────────────────────────────────────────────────────────┐
│                     Mininet (sudo)                        │
│                                                          │
│  Cluster A (S1)         Cluster B (S2)                   │
│  h_sensor1/2            h_sensor3/4                      │
│  h_camera1              h_camera2                        │
│  h_emerg                h_actuator                       │
│       │  (20 Mbps)            │  (20 Mbps)               │
│       ▼                       ▼                           │
│  [S3 core, low-lat] ──(50M)── [S4 core, high-BW]        │
│       │ (50 Mbps)                    │ (100 Mbps)         │
│       └──────────── [S5] ────────────┘                   │
│                  h_server1, h_server2                     │
└──────────────────────────────────────────────────────────┘
         ▲ OpenFlow (port 6633)
         │
┌────────┴─────────────────────────────────────────────────┐
│              Ryu Controller                               │
│  PacketIn → classify → DQN.select_action() → FlowMod    │
│  Stats loop (2s) → build state → agent.learn()           │
└──────────────────────────────────────────────────────────┘
         │                    │
┌────────┴───────┐   ┌────────┴────────┐
│  DQN Agent     │   │  Stats Collector│
│  (PyTorch CPU) │   │  (ovs-ofctl)    │
└────────────────┘   └─────────────────┘
         │
┌────────┴────────────────────────────────────────────────┐
│  Flask API (port 5000)  ← future                        │
│  Dashboard  (port 8080) ← future                        │
└─────────────────────────────────────────────────────────┘
```

---

## What We Built

### Phase 0 — Environment Setup

**Status: Complete**

The full software stack is installed and verified on a Manjaro laptop running inside a VS Code Flatpak sandbox. See [[Environment_Setup]] for the full installation log, error fixes, and NOPASSWD sudoers configuration.

**Installed:**
- Open vSwitch 3.7.1 (kernel module + systemd service)
- Mininet (pip package + compiled `mnexec` binary from AUR source)
- Ryu 4.34 (patched for Python 3.13 compatibility)
- PyTorch 2.11.0 CPU-only (190 MB wheel via `download.pytorch.org/whl/cpu`)
- Flask, NumPy, Pandas, Matplotlib, eventlet — all in `.venv`

---

### Phase 1 — Virtual Topology

**Status: Complete — verified at 0% packet loss**

A 2-tier, 5-switch IoT topology built in `mininet/iot_topology.py`.  
See [[Topology]] for port assignments, link parameters, and path definitions.

```
h_sensor1  (1M, 2ms) ─┐
h_sensor2  (1M, 2ms) ─┤
h_camera1  (10M, 5ms)─┤── S1 ──┬── (20M,5ms) ──► S3 ──┬── (50M,2ms) ──► S5 ── h_server1
h_emerg    (2M, 1ms) ─┘        └── (20M,8ms) ──► S4   │                    └── h_server2
                                                        └── (50M,3ms) ──► S4
h_sensor3  (1M, 2ms) ─┐                                cross-link
h_sensor4  (1M, 2ms) ─┤
h_camera2  (10M, 5ms)─┤── S2 ──┬── (20M,6ms) ──► S3
h_actuator (2M, 1ms) ─┘        └── (20M,7ms) ──► S4 ── (100M,5ms) ──► S5
```

**Verified:**
```
sudo .venv/bin/python3 mininet/iot_topology.py --test
*** Results: 0% dropped (90/90 received)
```

---

### Phase 2 — Stats Collector

**Status: Complete — 20 features verified**

`collector/stats_collector.py` polls all 5 OvS switches every 2 seconds using `ovs-ofctl dump-ports` and `ovs-ofctl dump-flows`, producing the 20-float state vector that feeds the DQN.  
See [[Stats_Collector]] for feature definitions, normalization, and the `get_state()` API.

| Feature range | What it captures |
|---------------|-----------------|
| 0–6 | Link utilisation (7 links) |
| 7–9 | Active flow counts per path (A / B / C) |
| 10–11 | Packet loss rate (Path A / B) |
| 12–13 | Jitter estimate (Path A / B) |
| 14–15 | Cumulative bytes transferred (Path A / B) |
| 16–19 | Time-of-day, util trend, priority flag, congestion flag |

---

### Phase 3 — DQN Agent

**Status: Architecture complete — not yet trained on real traffic**

`agent/dqn_agent.py` implements a **Dueling LSTM-DQN** with Double-DQN updates.  
See [[DQN_Agent]] for architecture details, reward function, and training configuration.

```
Input: (batch, 10, 20)  ← 10-step LSTM window, 20 features
  │
  └─► LSTM (hidden=128, 2 layers, dropout=0.2)
         │
         └─► last hidden state
                ├─► Value head:     FC(128→64→1)   → V(s)
                └─► Advantage head: FC(128→64→4)   → A(s,a)
                        │
                        └─► Q(s,a) = V(s) + A(s,a) - mean(A)
```

Training uses:
- Experience replay (10,000 capacity, batch 64)
- Double-DQN (online selects, target evaluates)
- Epsilon-greedy exploration (1.0 → 0.01, decay 0.995/step)
- Target network sync every 100 steps
- Gradient clipping (max norm 1.0)

---

### Phase 5 — Ryu SDN Controller

**Status: Complete**

`controller/ryu_controller.py` is a Ryu application that handles all OpenFlow events and drives the training loop.  
See [[Ryu_Controller]] for the full event handler descriptions and flow installation logic.

**Responsibilities:**
- On switch connect: install table-miss rule; install static server-distribution rules on S5
- On `PacketIn` for new IoT→server flow: classify flow, call `DQNAgent.select_action()`, install FlowMod rules on **every hop**
- Background loop (every 2 s): call `StatsCollector.get_state()`, compute reward for every active flow, call `agent.store()` + `agent.learn()`
- On `FlowRemoved`: clean up flow table, fire final `done=True` experience

---

### Phase 6 — Traffic Generators

**Status: Complete**

Two files: `traffic/generators.py` (standalone per-host scripts) and `traffic/scenario_runner.py` (orchestrator).  
See [[Traffic_Generators]] for traffic profiles and the 4-phase training scenario.

| Mode | DSCP | Rate | Simulates |
|------|------|------|-----------|
| `sensor` | AF41 | 1 pkt/s, 100 B | IoT temperature/humidity reading |
| `video` | AF31 | 5 Mbps UDP | Camera stream |
| `elephant` | BE | Full BW, TCP | Firmware update / bulk log upload |
| `emergency` | EF | 10 pkt/s, 50 B | Alarm / safety alert |
| `actuator` | EF | 5 pkt/s | Control command |

---

## How It All Works Together

This is the **end-to-end data flow** once all components are running:

```
1. sudo ryu-manager controller/ryu_controller.py   ← start controller
2. sudo python3 mininet/iot_topology.py            ← start topology
   └─► switches connect to Ryu → table-miss installed
3. sudo python3 traffic/scenario_runner.py         ← start traffic
   └─► generators send first packet → PacketIn arrives at Ryu

PacketIn loop (per new flow):
  Ryu sees PacketIn
    → state_buffer (last 10 snapshots) fed into DQNAgent.select_action()
    → action ∈ {PATH_A, PATH_B, PATH_C, DROP}
    → FlowMod rules installed on S1/S2 + S3/S4 + return path
    → subsequent packets forwarded in hardware (no more PacketIn)

Stats loop (every 2 s, background):
  StatsCollector.get_state()   ← polls ovs-ofctl on all 5 switches
    → patches features 7-9 (live path counts from controller's flow table)
    → patches feature 18 (priority flag)
    → appends new state to state_buffer
  For each active flow:
    compute_reward(prev_state, action, new_state)
    agent.store(state_seq, action, reward, next_state_seq, done=False)
  agent.learn()                ← one Double-DQN gradient step
    → epsilon decays
    → every 100 steps: target network sync
    → every 200 steps: save model_weights.pth

FlowRemoved event:
  flow_table.pop(flow_key)
  agent.store(..., done=True)  ← terminal experience
```

See [[Architecture]] for a fuller explanation of each arrow in this flow.

---

## Future Work

See [[Future_Work]] for detailed specifications of each remaining component.

| Phase | Component | What it does |
|-------|-----------|-------------|
| 4 | Flask REST API | Exposes agent state, reward history, active paths as JSON |
| 7 | D3.js Dashboard | Real-time visualisation of topology, path decisions, reward |
| 8 | Integration test | Full end-to-end run: Ryu + topology + traffic → model trains |
| 9 | Experiments | Compare DQN vs Shortest Path vs ECMP under 4 traffic scenarios |
| 10 | Demo prep | Recorded demo, result plots, final report |

The **critical next step** is running the first end-to-end integration test to verify the training loop works with real network feedback.
