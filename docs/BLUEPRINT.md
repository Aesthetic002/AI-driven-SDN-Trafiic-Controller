# Project Blueprint — AI-Driven SDN for IoT
### Team of 4 | 25-Day Delivery Plan

---

## Project Summary

Build an intelligent SDN network that uses a Dueling LSTM-DQN agent to route IoT traffic (sensors, video, elephant flows) across a Mininet-simulated topology. The system must demonstrably outperform Shortest Path and ECMP routing in mixed-traffic scenarios.

**Stack:** Mininet · Open vSwitch · Ryu · PyTorch · Flask · D3.js  
**Environment:** Single Manjaro laptop — all components run locally

---

## System Architecture (Quick Reference)

> **Single-machine setup:** No cloud VM. Ryu, Flask API, DQN training, Mininet, and Dashboard all run on the Manjaro laptop. Use `localhost` wherever the docs said "cloud VM".

```
  Cluster A (s1)          Cluster B (s2)
h_sensor1  (1M,2ms) ─┐  h_sensor3  (1M,2ms) ─┐
h_sensor2  (1M,2ms) ─┤  h_sensor4  (1M,2ms) ─┤
h_camera1  (10M,5ms)─┤  h_camera2  (10M,5ms)─┤
h_emergency(2M,1ms) ─┘  h_actuator (2M,1ms) ─┘
          │(20M)  (20M)│   │(20M)  (20M)│
          ▼             ▼   ▼             ▼
       [ S3: core low-lat ]──(50M,3ms)──[ S4: core high-BW ]
               │(50M,2ms)                    │(100M,5ms)
               └──────────── S5 ─────────────┘
                          h_server1, h_server2

Ryu Controller (localhost:6633) ◀── PacketIn / FlowMod
    └─▶ Flask API (localhost:5000)
            └─▶ DQN Agent — 20-feature state → 4 actions
                    Path A (S3, low latency) | Path B (S4, high BW)
                    Path C (cross-link overflow) | Drop
Stats Collector ──▶ Flask API + Dashboard (localhost:8080)
```

**Critical path:** Stats Collector → DQN Agent → Flask API → Ryu Controller  
Everything else (topology, dashboard, traffic gen) can develop in parallel.

> **Topology change from original spec:** Upgraded to 5-switch 2-tier layout.
> DQN now has **4 actions** (Path A / B / C / Drop) instead of 3.

---

## Team Assignments

---

### Member 1 — Network & Infrastructure

**Domain:** Mininet topology, Open vSwitch, stats pipeline, traffic generation

| Phase | Days | Deliverable |
|-------|------|-------------|
| 0 — Env Setup | 1–2 | Mininet + OvS + PyTorch + Ryu installed; `sudo mn --test pingall` passes |
| 1 — Virtual Topology | 3–4 | `mininet/iot_topology.py` — 5-switch 2-tier topology, 10 hosts, 3 paths |
| 2 — Stats Collector | 5 | `collector/stats_collector.py` — 20 features as JSON every 2s |
| 6 — Traffic Generators | 14 | `traffic/generators.py` + `traffic/scenario_runner.py` |

**Files you own:**
- `mininet/iot_topology.py`
- `collector/stats_collector.py`
- `traffic/generators.py`
- `traffic/scenario_runner.py`

**Key specs:**
- Topology: h_sensor1/2, h_camera → S1 → S2 (Path A, 5 Mbps 10ms) / S3 (Path B, 5 Mbps 15ms) → h_server
- Sensor links: 1 Mbps, 2ms | Camera link: 10 Mbps, 5ms
- Controller IP: cloud VM, port 6633
- Stats poll interval: 2 seconds via `ovs-ofctl dump-ports` + `dump-flows`
- 20 features: 3 link utils, 3 queue depths, 2 active flows, 2 packet loss, 2 jitter, 2 bytes/path, ToD, util trend, priority flag, global jitter
- Traffic scenarios: Phase 1 (0–60s sensors only) → Phase 2 (60–120s +video) → Phase 3 (120–180s +elephant) → Phase 4 (180–240s recovery)

**Contract with Member 2:** Stats collector must expose a callable `get_state() → dict[20 floats]` or write to a shared endpoint. Agree on the exact feature ordering/normalization by Day 5.

**Done criteria:**
- `python3 stats_collector.py` prints 20-field JSON every 2s while Mininet runs
- All 3 traffic types run simultaneously; Wireshark shows correct DSCP markings

---

### Member 2 — AI / ML Engineer

**Domain:** DQN agent architecture, training pipeline, model weights

| Phase | Days | Deliverable |
|-------|------|-------------|
| 0 — Env Setup (shared) | 1–2 | PyTorch + Ryu installed; `import torch; import ryu` passes in `.venv` |
| 3a — Model Architecture | 6–7 | `agent/dqn_agent.py` — LSTM + Dueling DQN |
| 3b — Replay Buffer | 6–7 | `agent/replay_buffer.py` — 10k capacity, batch-64 sampling |
| 3c — Reward Function | 8 | `agent/reward.py` — multi-objective weighted reward |
| 3d — Training Loop | 8–9 | `agent/train.py` — 3–5k episodes, saves `model_weights.pth` |

**Files you own:**
- `agent/dqn_agent.py`
- `agent/replay_buffer.py`
- `agent/reward.py`
- `agent/train.py`
- `model_weights.pth` (artifact)

**Key specs:**
```
Input: 10 × 20 state sequence (LSTM window)
LSTM:  hidden=256
FC:    256 → 128 (shared), BatchNorm + Dropout
Value head:     128 → 1      → V(s)
Advantage head: 128 → 3      → A(s, a)
Q(s,a) = V(s) + A(s,a) - mean(A)

Replay buffer: capacity 10,000 | batch size 64
ε: 1.0 → 0.01 (decay 0.5%/episode)
Target network sync: every 100 steps
Gradient clipping: max norm = 1.0
Reward: 0.4×latency + 0.3×reliability + 0.2×throughput + 0.1×fairness × priority_mult (5.0 for emergency)
```

**Contract with Member 3:** Expose a clean `agent.select_action(state_seq) → int` and `agent.store_experience(...)` interface. Member 3's Flask API wraps these directly.

**Done criteria:**
- Loss curve plots downward over training
- ε reaches < 0.01 by episode 3,000
- `model_weights.pth` loads and runs inference without error

**Note:** Kick off training overnight as early as possible — it takes 2–7 hours.

---

### Member 3 — Backend / SDN Controller

**Domain:** Flask REST API bridge, Ryu SDN controller, OpenFlow rules

| Phase | Days | Deliverable |
|-------|------|-------------|
| 4 — Flask API | 10 | `api/app.py` — 4 endpoints wrapping the DQN agent |
| 5 — Ryu Controller | 11–13 | `controller/ryu_controller.py` — PacketIn → AI → FlowMod pipeline |

**Files you own:**
- `api/app.py`
- `controller/ryu_controller.py`

**Flask API endpoints:**

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/predict` | POST | `{"state": [20 floats]}` | `{"action": 0/1/2, "q_values": [...]}` |
| `/train` | POST | experience tuple | `{"status": "ok"}` |
| `/status` | GET | — | `{"epsilon": float, "episode": int, "version": str}` |
| `/policy` | POST | `{"mode": "dqn"/"shortest_path"/"ecmp"}` | `{"status": "ok"}` |

**Ryu controller flow:**
1. `packet_in_handler`: parse headers → classify flow (sensor/video/elephant)
2. Collect state from stats collector → POST `/predict`
3. Install FlowMod: `match(src_ip, dst_ip, proto) → output_port`, `idle_timeout=30`
4. After flow ends: compute reward → POST `/train`

**Flow classification:**
- Sensor: UDP, src=sensor IPs, pkt < 200B → DSCP 46 (high)
- Video: UDP, dst_port=5004, rate > 500 kbps → DSCP medium
- Elephant: TCP, large payload, duration > 5s → DSCP low

**Done criteria:**
- `curl -X POST localhost:5000/predict -d '{"state": [...]}'` returns `{"action": 1, "q_values": [...]}`
- `ryu-manager ryu_controller.py` — new flows get forwarded; `ovs-ofctl dump-flows s1` shows entries
- FlowMod installed in < 50ms from PacketIn

---

### Member 4 — Frontend, Experiments & Integration Lead

**Domain:** Live dashboard, experiment runner, integration, demo prep

| Phase | Days | Deliverable |
|-------|------|-------------|
| 7 — Dashboard | 15–17 | `dashboard/server.py` + `dashboard/static/index.html` |
| 8 — Integration | 18–20 | Full end-to-end working; integration checklist signed off |
| 9 — Experiments | 21–23 | 9-run comparison table + charts |
| 10 — Demo Prep | 24–25 | `demo_runbook.md`; system survives 30-min live demo |

**Files you own:**
- `dashboard/server.py`
- `dashboard/static/index.html`
- `experiments/runner.py`
- `experiments/plot_results.py`
- `demo_runbook.md`

**Dashboard specs (Flask-SocketIO + D3.js):**
- Stats streamed every 1s via WebSocket
- `/topology` endpoint: JSON graph (nodes + edges with utilization %)
- Panels: topology (colored links), latency line chart, AI stats (ε/episode/policy), flow table
- Link colors: Green < 30% | Yellow 30–70% | Red > 70%

**Experiment matrix (9 runs × 3 min each):**

|  | Scenario A (Sensors) | Scenario B (S+Video) | Scenario C (All) |
|--|--|--|--|
| Shortest Path | Run 1 | Run 2 | Run 3 |
| ECMP | Run 4 | Run 5 | Run 6 |
| AI/DQN | Run 7 | Run 8 | Run 9 |

**Metrics per run:** Mean/P95/P99 sensor latency (ms), video throughput + jitter, elephant completion time, packet loss %, Jain's Fairness Index.

**Integration checklist (Phase 8):**
- [ ] PacketIn → API → FlowMod < 50ms
- [ ] Stats collector feeding 20 features continuously
- [ ] Online fine-tuning active during live run
- [ ] Dashboard reflects real switch state
- [ ] `/policy` switch takes effect within 5 seconds

**Demo hardening (Phase 10):**
- `supervisord`/`systemd` auto-restart for Flask API
- OvS reconnect watchdog for Ryu
- Pre-warm replay buffer with 500 synthetic experiences
- Backup screen recording

---

## Startup Order (Integration Reference)

All commands run on the single Manjaro laptop. Use `source .venv/bin/activate` first.

```
1. python3 api/app.py                         # Flask API + DQN Agent  (Member 3 → Member 2)
2. ryu-manager controller/ryu_controller.py   # Ryu SDN Controller     (Member 3)
3. python3 collector/stats_collector.py       # Stats pipeline         (Member 1)
4. sudo python3 mininet/iot_topology.py       # Mininet topology       (Member 1)
5. python3 dashboard/server.py                # Live dashboard         (Member 4)
6. python3 traffic/scenario_runner.py         # Traffic scenarios      (Member 1)
```

---

## Timeline Overview

| Days | Member 1 | Member 2 | Member 3 | Member 4 |
|------|----------|----------|----------|----------|
| 1–2 | Env setup (laptop) | Env setup (VM) | — | — |
| 3–4 | Mininet topology | — | — | — |
| 5 | Stats collector | — | — | — |
| 6–9 | — | DQN agent + training | — | — |
| 10 | — | Training runs | Flask API | — |
| 11–13 | — | Training runs | Ryu controller | — |
| 14 | Traffic generators | — | — | — |
| 15–17 | — | — | — | Dashboard |
| 18–20 | Integration | Integration | Integration | **Lead** |
| 21–23 | — | — | — | Experiments |
| 24–25 | Support | Support | Support | Demo prep |

---

## Interface Contracts

These are the boundaries between team members. Agree on these before Day 6.

### Contract 1 — Member 1 → Member 2 (state format)
```python
# stats_collector.py must expose:
def get_state() -> list[float]:  # exactly 20 values, normalized [0,1]
    # order: [link1_util, link2_util, link3_util,
    #         q1_depth, q2_depth, q3_depth,
    #         flows_pathA, flows_pathB,
    #         loss_pathA, loss_pathB,
    #         jitter_pathA, jitter_pathB,
    #         bytes_pathA, bytes_pathB,
    #         time_of_day, util_trend,
    #         priority_flag, global_jitter,
    #         ... (remaining 2 TBD jointly)]
```

### Contract 2 — Member 2 → Member 3 (agent interface)
```python
# agent must expose:
agent.select_action(state_seq: list[list[float]]) -> int  # 0=PathA, 1=PathB, 2=Drop
agent.store_experience(state_seq, action, reward, next_seq, done)
agent.get_status() -> dict  # {"epsilon": ..., "episode": ..., "version": ...}
```

### Contract 3 — Member 3 → Member 4 (API/WebSocket)
```python
# Flask API must serve:
# GET /topology → {"nodes": [...], "edges": [..., "utilization": 0.0–1.0]}
# WebSocket event "stats_update" → {timestamp, link_utils, active_flows, ai_stats}
```

---

## Risk Register

| Risk | Owner | Mitigation |
|------|-------|------------|
| LSTM training diverges | M2 | Gradient clipping (norm=1.0); reduce LR; check BatchNorm |
| Mininet ↔ VM connectivity fails | M1 + M3 | Test OpenFlow TCP:6633 tunnel on Day 2 |
| Stats collector misaligns feature order | M1 + M2 | Lock feature schema in a shared `constants.py` |
| Dashboard WebSocket lag during demo | M4 | Buffer 1s stats server-side; test under 3-traffic load |
| Flask API crashes mid-demo | M3 + M4 | supervisord auto-restart; `/status` healthcheck |
| Training takes > 7 hours | M2 | Start training on Day 6 end-of-day; run overnight |
