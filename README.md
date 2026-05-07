# AI-Driven SDN for IoT — Project Overview

An end-to-end software-defined network controller that uses a **Dueling LSTM-DQN** reinforcement-learning agent to route IoT traffic across a virtual 5-switch Mininet topology, all running on a single Manjaro laptop.

---

## What It Does

The system simulates an IoT network with sensors, cameras, and emergency devices on two access clusters (Cluster A and Cluster B). A Ryu SDN controller intercepts every new flow, asks the DQN agent which path to assign it, and installs OpenFlow rules across the switches. Every 2 seconds the agent observes a 20-feature state vector, computes a shaped reward, stores the experience in a replay buffer, and performs a Double-DQN gradient step. Weights and the replay buffer persist across runs so the agent improves over time.

---

## Quick Start

> All commands must be run in a **native terminal** (not inside the Flatpak VS Code sandbox) because Mininet requires `sudo`.

### First-time setup (once only)

```bash
# 1. System packages — in native terminal
sudo pacman -S --noconfirm openvswitch iperf3 python-pip

# 2. Start OvS
sudo systemctl enable --now ovsdb-server ovs-vswitchd

# 3. Python environment — from project root
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Patch Ryu for Python 3.10+ compatibility
python3 scripts/patch_ryu.py
```

See [[Environment_Setup]] for the full installation guide including known errors.

### Run a training session

```bash
# From project root, native terminal
sudo .venv/bin/python3 train.py --phase-secs 60
```

This starts all five components in the right order, runs 4 traffic phases (4 × 60 s = 4 min), prints a summary, and saves model weights + replay buffer automatically.

**Comparison mode examples:**

```bash
# Default: DQN controls routing + shadow baseline comparison
sudo .venv/bin/python3 train.py --phase-secs 60 --routing-mode dqn --baseline-policy least_utilized

# Baseline-only control run (for A/B demo)
sudo .venv/bin/python3 train.py --phase-secs 60 --routing-mode baseline --baseline-policy round_robin
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--phase-secs N` | 60 | Seconds per traffic phase (total = 4 × N) |
| `--no-dashboard` | off | Skip the dashboard HTTP server |
| `--routing-mode {dqn,baseline}` | dqn | Select which policy controls live flow installs |
| `--baseline-policy {shortest_path,ecmp_hash,round_robin,least_utilized,random}` | least_utilized | Baseline policy for baseline mode + shadow comparison |
| `--no-shadow-compare` | off | Disable DQN-vs-baseline shadow metrics |

### Check progress while running

- Dashboard: http://localhost:8080
- REST API: http://localhost:5000
- Full snapshot: http://localhost:5000/api/snapshot
- Comparison snapshot: http://localhost:5000/api/compare/current
- Comparison history: http://localhost:5000/api/compare/history

---

## Project Layout

```
EL2k26/
├── train.py                    # Single entry point — starts everything
├── constants.py                # Shared constants (IPs, ports, hyperparams)
├── requirements.txt
├── setup.sh                    # Full environment setup script
├── scripts/
│   └── patch_ryu.py            # Patches Ryu for Python 3.10+ compat
├── mininet/
│   └── iot_topology.py         # Virtual 5-switch, 10-host topology
├── collector/
│   └── stats_collector.py      # OvS poller → 20-feature state vector
├── agent/
│   └── dqn_agent.py            # Dueling LSTM-DQN + ReplayBuffer
├── controller/
│   └── ryu_controller.py       # Ryu app: PacketIn → DQN → FlowMod
├── traffic/
│   ├── generators.py           # Per-host traffic generators
│   └── scenario_runner.py      # 4-phase traffic orchestration
├── api/
│   ├── app.py                  # Flask REST API + SSE stream
│   └── shared_state.py         # Thread-safe IPC bridge
├── dashboard/
│   ├── index.html              # D3.js live dashboard
│   └── serve.py                # Simple HTTP server for dashboard
└── docs/
    └── phase 3 - Implementation/
        ├── How_To_Run.md       # Step-by-step run guide
        ├── Architecture.md     # System architecture + data flow
        ├── Modules_Reference.md# Every file documented
        ├── State_And_Reward.md # 20-feature state + reward function
        ├── Training_And_Persistence.md  # Training loop + weight/buffer saving
        ├── API_And_Dashboard.md         # REST API endpoints + dashboard panels
        └── Troubleshooting.md  # Known errors and fixes
```

---

## Component Summary

| Component | File | Purpose |
|-----------|------|---------|
| Orchestrator | `train.py` | Starts all services in order |
| Constants | `constants.py` | Single source of truth for all values |
| Topology | `mininet/iot_topology.py` | 5-switch virtual network |
| Stats Collector | `collector/stats_collector.py` | Polls OvS → 20 features |
| DQN Agent | `agent/dqn_agent.py` | Neural net + replay buffer |
| Ryu Controller | `controller/ryu_controller.py` | OpenFlow events + training loop |
| Traffic Generators | `traffic/generators.py` | Sensor, video, elephant, emergency |
| Scenario Runner | `traffic/scenario_runner.py` | 4-phase traffic script |
| Flask API | `api/app.py` | REST + SSE endpoints |
| Shared State | `api/shared_state.py` | Thread-safe IPC |
| Dashboard | `dashboard/index.html` | D3.js live visualisation |

---

## Runtime Files

These files are created during a run and persist across runs:

| File | Created by | Purpose |
|------|-----------|---------|
| `model_weights.pth` | Ryu controller | Neural network weights + epsilon + step count |
| `/tmp/sdn_replay_buffer.pkl` | Ryu controller | Replay buffer (up to 10,000 transitions) |
| `/tmp/sdn_runtime_state.json` | Ryu controller | Live state snapshot read by Flask API |

---

## Further Reading

- [[How_To_Run]] — Detailed run guide with all commands
- [[Architecture]] — Full system architecture diagram
- [[Modules_Reference]] — Every Python file explained
- [[State_And_Reward]] — The 20 state features and reward shaping
- [[Training_And_Persistence]] — How training accumulates over runs
- [[API_And_Dashboard]] — REST API reference + dashboard panel guide
- [[Troubleshooting]] — Known errors and their fixes
- [[Environment_Setup]] — Full installation log
