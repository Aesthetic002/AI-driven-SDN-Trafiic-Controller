# Phase-wise Implementation Plan: AI-Driven SDN for IoT

---

## Phase 0 — Environment Setup (Day 1-2)

**Goal:** All infrastructure ready before writing a single line of project code.

### Cloud VM (Ubuntu 20.04/22.04)

```bash
# Python + PyTorch
sudo apt update && sudo apt install -y python3 python3-pip git
pip3 install torch torchvision flask ryu numpy pandas matplotlib

# Ryu SDN Controller
pip3 install ryu eventlet
```

### Laptop / Edge (Manjaro Linux)

```bash
# Mininet + Open vSwitch
sudo pacman -S mininet openvswitch
sudo systemctl start ovsdb-server ovs-vswitchd

# Traffic tools
sudo pacman -S iperf3 wireshark-qt
```

**Deliverable:** `python3 -c "import torch; import ryu"` runs without errors on both machines.

---

## Phase 1 — Virtual Network Topology (Day 3-4)

**Goal:** Mininet network matches the documented 3-switch dual-path IoT topology.

**File:** `mininet/iot_topology.py`

```
h_sensor1 ─┐
h_sensor2 ─┤── S1 ──── S2 (5Mbps, 10ms) ──── h_server
h_camera  ─┘      └─── S3 (5Mbps, 15ms) ──── h_server2
```

Key configs per the docs:

- Sensor links: 1 Mbps, 2ms
- Camera link: 10 Mbps, 5ms
- Path A (S1→S2): 5 Mbps, 10ms
- Path B (S1→S3): 5 Mbps, 15ms
- Controller IP: cloud VM, port 6633

**Test:** `sudo mn --test pingall` shows all hosts reachable.

---

## Phase 2 — Statistics Collector (Day 5)

**Goal:** Reliable stream of the 20 state features the AI needs.

**File:** `collector/stats_collector.py`

Polls OvS every 2 seconds via `ovs-ofctl dump-ports` and `ovs-ofctl dump-flows`, computes:

|Feature Group|Count|Source|
|---|---|---|
|Link utilization (3 links)|3|port byte counters|
|Queue depths (3 queues)|3|queue stats|
|Active flows per path|2|flow table|
|Packet loss per path|2|TX vs RX counters|
|Jitter per path|2|delay variance|
|Bytes so far per path|2|flow counters|
|Time of day (normalized)|1|system clock|
|Utilization trend (delta)|1|previous vs current|
|Priority flag|1|parsed from DSCP|
|Global jitter|1|avg across paths|
|**Total**|**20**||

**Test:** `python3 stats_collector.py` prints a JSON with 20 numeric fields every 2s.

---

## Phase 3 — DQN AI Agent (Day 6-9)

**Goal:** Fully trained agent that maps 20-feature state → 1 of 3 actions (Path A / Path B / Drop).

**File:** `agent/dqn_agent.py`

### 3a — Model Architecture

```python
class DQNAgent(nn.Module):
    # LSTM layer processes last 10 states (20-second window)
    # → hidden[256]
    # Dueling heads:
    #   Value stream:     hidden[256] → [128] → [1]
    #   Advantage stream: hidden[256] → [128] → [3]
    # Output: Q(s,a) = V(s) + A(s,a) - mean(A)
```

### 3b — Replay Buffer

```python
class ReplayBuffer:
    # capacity: 10,000 transitions
    # stores (state_seq, action, reward, next_state_seq, done)
    # sample_batch(64) for training
```

### 3c — Multi-objective Reward

```python
reward = (0.4 × latency_reward
        + 0.3 × reliability_reward
        + 0.2 × throughput_reward
        + 0.1 × fairness_reward)
        × priority_multiplier  # 5.0 for emergency flows
```

### 3d — Training Loop

```python
# 3,000–5,000 episodes
# ε: 1.0 → 0.01 (decays 0.5% per episode)
# Target network sync every 100 steps
# Gradient clipping (max norm = 1.0) for LSTM stability
# Save model_weights.pth when ε < 0.01
```

**Test:** Loss curve plots downward; epsilon reaches < 0.01 by episode 3,000.

---

## Phase 4 — Flask REST API Bridge (Day 10)

**Goal:** Ryu controller can query the AI agent over HTTP.

**File:** `api/app.py`

|Endpoint|Method|Purpose|
|---|---|---|
|`/predict`|POST|Send 20-feature state, receive action (0/1/2)|
|`/train`|POST|Submit experience tuple for replay buffer|
|`/status`|GET|Returns epsilon, episode count, model version|
|`/policy`|POST|Switch between `dqn` / `shortest_path` / `ecmp`|

**Test:** `curl -X POST localhost:5000/predict -d '{"state": [...]}'` returns `{"action": 1, "q_values": [...]}`.

---

## Phase 5 — Ryu SDN Controller (Day 11-13)

**Goal:** Controller that classifies traffic, queries AI, and installs FlowMod rules.

**File:** `controller/ryu_controller.py`

### Event Handlers

```python
@set_ev_cls(ofp_event.EventOFPPacketIn)
def packet_in_handler(event):
    # 1. Parse packet headers
    flow_type = classify_flow(pkt)   # sensor / video / elephant

    # 2. Collect 20-feature state from stats collector
    state = get_network_state()

    # 3. Query Flask API for action
    action = requests.post('http://vm:5000/predict', json=state).json()['action']

    # 4. Install FlowMod: match(src_ip, dst_ip, proto) → output_port
    install_flow_rule(datapath, match, action_port, idle_timeout=30)

    # 5. Submit reward to API after flow completes
```

### Flow Classification Rules

- Sensor: UDP, src=sensor IPs, packet size < 200 bytes → priority high (DSCP 46)
- Video: UDP, dst_port=5004, rate > 500 kbps → priority medium
- Elephant: TCP, large payload, duration > 5s → priority low

**Test:** `ryu-manager ryu_controller.py` — new flows get forwarded; `ovs-ofctl dump-flows s1` shows entries.

---

## Phase 6 — Traffic Generators (Day 14)

**Goal:** Reproducible traffic scenarios matching the 3-phase demo narrative.

**File:** `traffic/generators.py`

```python
def gen_sensor_traffic(host, interval=5, pkt_size=100):
    # UDP flood: 100-byte packets every 5s

def gen_video_traffic(host, target_mbps=3):
    # iperf3 UDP at 3 Mbps continuously

def gen_elephant_flow(host, size_mb=500):
    # iperf3 TCP, 500 MB bulk transfer
```

**File:** `traffic/scenario_runner.py`

```
Phase 1 (0–60s):   Only sensors
Phase 2 (60–120s): Sensors + Video
Phase 3 (120–180s): Sensors + Video + Elephant flow
Phase 4 (180–240s): Elephant ends, recovery
```

**Test:** All three traffic types run simultaneously; Wireshark shows correct DSCP markings.

---

## Phase 7 — Live Dashboard (Day 15-17)

**Goal:** Browser-accessible real-time view during demo.

**Files:** `dashboard/server.py`, `dashboard/static/index.html`

### Backend (Flask + WebSocket)

- Streams stats every 1 second via `flask-socketio`
- Exposes `/topology` endpoint (JSON graph: nodes + edges with utilization)

### Frontend (D3.js)

|Panel|Shows|
|---|---|
|Topology graph|Nodes (hosts/switches) + colored links (green/yellow/red by utilization)|
|Latency chart|Live line chart per traffic type (last 60s)|
|AI stats|Current ε, episode, active policy|
|Flow table|Which flows → which path (updated every 2s)|

Link color thresholds (from docs):

- 🟢 Green: < 30% utilization
- 🟡 Yellow: 30–70%
- 🔴 Red: > 70%

**Test:** Open `localhost:8080` while Mininet runs — topology updates in real-time.

---

## Phase 8 — Integration & End-to-End Test (Day 18-20)

**Goal:** All components running together as one system.

### Startup Order (Critical)

```
1. Cloud VM: python3 api/app.py              # Flask API + AI agent
2. Cloud VM: ryu-manager controller/ryu_controller.py
3. Laptop:   python3 collector/stats_collector.py
4. Laptop:   sudo python3 mininet/iot_topology.py
5. Laptop:   python3 dashboard/server.py
6. Laptop:   python3 traffic/scenario_runner.py
```

### Integration Checklist

- [ ]  PacketIn → API call → FlowMod installed in < 50ms
- [ ]  Stats collector feeding 20 features to API continuously
- [ ]  AI agent training on live experience (online fine-tuning)
- [ ]  Dashboard reflects real switch state
- [ ]  Policy switch (`/policy`) takes effect within 5 seconds

---

## Phase 9 — Experiments & Evaluation (Day 21-23)

**Goal:** Reproducible numbers comparing the 3 routing policies across 3 scenarios.

**File:** `experiments/runner.py`

### Experiment Matrix (9 runs × 3 minutes each)

||Scenario A (Sensors only)|Scenario B (Sensors+Video)|Scenario C (All traffic)|
|---|---|---|---|
|**Shortest Path**|Run 1|Run 2|Run 3|
|**ECMP**|Run 4|Run 5|Run 6|
|**AI/DQN**|Run 7|Run 8|Run 9|

### Metrics Collected Per Run

- Mean / P95 / P99 sensor latency (ms)
- Video throughput (Mbps) and jitter (ms)
- Elephant flow completion time (s)
- Packet loss rate (%)
- Jain's Fairness Index

**File:** `experiments/plot_results.py` — generates comparison bar/line charts.

**Expected outcome:** AI outperforms SP/ECMP in Scenario C (all traffic) by 50–80% on sensor latency.

---

## Phase 10 — Hardening & Demo Prep (Day 24-25)

**Goal:** System survives a 30-minute live demo without manual intervention.

- Add auto-restart for Flask API crashes (`supervisord` or `systemd` service)
- Watchdog that reconnects Ryu to controller if OvS loses connection
- Pre-warm replay buffer with 500 synthetic experiences before live run
- Write `demo_runbook.md`: exact commands, what to say at each phase, troubleshooting table
- Record a backup screen capture in case hardware fails during demo

---

## Summary Timeline

|Phase|Days|Deliverable|
|---|---|---|
|0 — Setup|1–2|Working dev environment|
|1 — Topology|3–4|Mininet 3-switch network|
|2 — Stats|5|20-feature state stream|
|3 — DQN Agent|6–9|Trained model weights|
|4 — API|10|Flask bridge tested|
|5 — Controller|11–13|Ryu routing with AI|
|6 — Traffic|14|3-scenario runner|
|7 — Dashboard|15–17|Live D3.js topology view|
|8 — Integration|18–20|Full end-to-end working|
|9 — Experiments|21–23|9-run comparison table|
|10 — Demo Prep|24–25|Polished, resilient demo|

**Total: ~25 days** from zero code to demo-ready.

---

The critical path is **Phases 3 → 4 → 5** (AI agent → API → controller). Everything else can be developed in parallel once Phase 2 (stats) is working. Start coding Phase 3 first — training takes 2–7 hours and should be kicked off as early as possible.