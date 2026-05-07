# How To Run
### Complete step-by-step guide for every mode

---

## Table of Contents

- [[#Prerequisites|Prerequisites]]
- [[#First-Time Setup|First-Time Setup]]
- [[#Running a Full Training Session|Running a Full Training Session]]
- [[#What Happens During a Run|What Happens During a Run]]
- [[#Running Individual Components|Running Individual Components]]
- [[#Mock Mode (No Mininet)|Mock Mode (No Mininet)]]
- [[#Checking Training Progress|Checking Training Progress]]
- [[#Stopping the System|Stopping the System]]
- [[#After the Run|After the Run]]
- [[#Repeated Runs — Accumulated Learning|Repeated Runs — Accumulated Learning]]

---

## Prerequisites

- Manjaro Linux (or any Arch-based distro)
- Open vSwitch installed and running
- Mininet with the `mnexec` binary compiled
- Python 3.11–3.13 virtual environment with all packages installed
- Ryu patched for Python 3.10+ compatibility

> **Flatpak VS Code users:** Any command requiring `sudo` MUST be run in a **native terminal** (Konsole, xterm, etc.) — not inside VS Code's integrated terminal. VS Code runs in a Flatpak sandbox where `sudo` does not exist.

---

## First-Time Setup

Run these commands once after cloning the repository.

### Step 1 — System packages (native terminal, needs sudo)

```bash
sudo pacman -S --noconfirm openvswitch iperf3 net-tools iproute2 python-pip
```

If there are `libatomic` conflicts:

```bash
sudo pacman -S --overwrite "/usr/lib/libatomic*" \
               --overwrite "/usr/lib/libgcc*" \
               --overwrite "/usr/lib/libstdc*" \
               openvswitch
```

### Step 2 — Start Open vSwitch services

```bash
sudo systemctl enable --now ovsdb-server ovs-vswitchd

# Verify
sudo ovs-vsctl show
# Should print: ovs_version: "3.x.x" (no error)
```

### Step 3 — Python virtual environment (from project root)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

### Step 4 — Patch Ryu

Ryu 4.34 was written for Python 3.9 and uses APIs removed in 3.10. The patch script fixes all of them in-place:

```bash
python3 scripts/patch_ryu.py
# Should print: "ryu import: OK"
```

### Step 5 — Verify installation

```bash
source .venv/bin/activate

# Python imports
python3 -c "import torch; print('torch', torch.__version__)"
python3 -c "import ryu;   print('ryu ok')"
python3 -c "import flask; print('flask', flask.__version__)"

# Stats collector with synthetic data (no Mininet needed)
python3 collector/stats_collector.py --mock --once

# Topology test (native terminal, ~40 s — runs STP then pingall)
sudo .venv/bin/python3 mininet/iot_topology.py --test
# Expected: "*** Results: 0% dropped (90/90 received)"
```

---

## Running a Full Training Session

This is the main command. It starts every component in the correct order and runs the 4-phase traffic scenario.

```bash
# Native terminal — must be run with sudo
sudo .venv/bin/python3 train.py --phase-secs 60
```

Default: 4 phases × 60 s = **4 minutes total**.

For a quick test run:

```bash
sudo .venv/bin/python3 train.py --phase-secs 10
# Total: 40 seconds
```

For a longer training session (more gradient steps):

```bash
sudo .venv/bin/python3 train.py --phase-secs 300
# Total: 20 minutes — more flows, more learning
```

Skip the dashboard (lighter CPU):

```bash
sudo .venv/bin/python3 train.py --phase-secs 60 --no-dashboard
```

---

## What Happens During a Run

`train.py` starts the components in this exact order:

```
1. Ryu controller subprocess   → listens on :6633 (OpenFlow)
   waits up to 30s for Ryu port to open

2. Flask API thread             → http://localhost:5000
   starts _file_pump background thread (polls /tmp/sdn_runtime_state.json)

3. Dashboard HTTP server        → http://localhost:8080

4. Mininet + traffic scenario   (blocks until all 4 phases done)
   4a. Build topology (5 switches, 10 hosts)
   4b. net.start() — OvS bridges created, switches connect to Ryu
   4c. Wait 2s for switch registration
   4d. Start UDP/TCP servers on h_server1, h_server2
   4e. Phase 1 (0–60s):   4 sensors → server
   4f. Phase 2 (60–120s): +2 cameras at 5 Mbps
   4g. Phase 3 (120–180s): +elephant TCP 150 MB, +emergency, +actuator
   4h. Phase 4 (180–240s): recovery — light 2 Mbps video only

5. Print summary (from /tmp/sdn_runtime_state.json)
6. Shutdown
```

Every 2 seconds during the run, the Ryu controller:
- Polls all 5 OvS switches for port counters and flow tables
- Builds a 20-feature state vector
- Computes shaped rewards for active flows
- Stores transitions in the replay buffer
- Runs one gradient update (if buffer ≥ 64 transitions)
- Saves weights to `model_weights.pth`
- Saves replay buffer to `/tmp/sdn_replay_buffer.pkl`
- Writes JSON snapshot to `/tmp/sdn_runtime_state.json` (picked up by Flask)

---

## Running Individual Components

### Ryu controller only (no Mininet)

Useful when you want to run Mininet separately or connect physical switches.

```bash
source .venv/bin/activate
python3 -m ryu.cmd.manager \
    --ofp-tcp-listen-port 6633 \
    controller/ryu_controller.py
```

### Mininet topology only (interactive CLI)

```bash
# Requires Ryu to be running first
sudo .venv/bin/python3 mininet/iot_topology.py --cli
```

```bash
# Without Ryu (standalone OVS learning switch mode)
sudo .venv/bin/python3 mininet/iot_topology.py --cli
# Falls back to OVSController automatically
```

### Connectivity test

```bash
sudo .venv/bin/python3 mininet/iot_topology.py --test
# Runs pingall, prints packet loss %, exits
```

### Stats collector (standalone)

```bash
# Live (requires Mininet to be running)
python3 collector/stats_collector.py

# Synthetic data — no Mininet needed
python3 collector/stats_collector.py --mock

# One snapshot then exit
python3 collector/stats_collector.py --mock --once
```

### Flask API (mock mode — no controller needed)

```bash
python3 api/app.py --mock
# → http://localhost:5000
# Pushes synthetic oscillating data every 2s
```

### Flask API (production mode — reads Ryu's JSON file)

```bash
python3 api/app.py
# → http://localhost:5000
# Reads /tmp/sdn_runtime_state.json every 1s
```

### Dashboard only

```bash
cd dashboard && python3 -m http.server 8080
# → http://localhost:8080
```

### DQN agent smoke test

```bash
python3 agent/dqn_agent.py
# Fills replay buffer, runs one gradient step, save/load round-trip
```

---

## Mock Mode (No Mininet)

When you want to test the API or dashboard without running Mininet:

```bash
# Terminal 1 — Flask with synthetic data
python3 api/app.py --mock

# Terminal 2 — Dashboard
cd dashboard && python3 -m http.server 8080

# Open http://localhost:8080
# All panels animate with synthetic data
```

---

## Checking Training Progress

### Dashboard (live)

Open http://localhost:8080 during a run. Updates every 2 seconds via SSE.

Panels:
- **Epsilon** — exploration rate, starts at 1.0, decays toward 0.01
- **Learn Steps** — gradient updates performed so far
- **Total Reward** — cumulative shaped reward
- **Last Loss** — Huber loss from most recent gradient step
- **Flow Count** — active flows in the DQN's tracking table
- **Topology** — D3 force graph, links coloured by path choice
- **Reward chart** — last 200 reward values
- **Loss chart** — last 200 loss values
- **Path decisions** — bar chart (Path A / B / C / Drop counts)
- **Link utilisation** — all 7 core links
- **Active flows table** — src, dst, path, age

### REST API (snapshot)

```bash
curl http://localhost:5000/api/snapshot | python3 -m json.tool
```

### Runtime state file (raw)

```bash
cat /tmp/sdn_runtime_state.json | python3 -m json.tool
```

### Training summary (printed at the end of train.py)

```
============================================================
  Training complete in 245s
  Learn steps   : 87
  Epsilon       : 0.6503
  Total reward  : 335.69
  Last loss     : 2.547819
  Path A flows  : 52
  Path B flows  : 18
  Path C flows  : 7
  Dropped flows : 1
============================================================
```

---

## Stopping the System

Press `Ctrl-C` in the terminal running `train.py`. The signal handler:
1. Terminates the Ryu subprocess
2. Ryu's `close()` method saves final weights and replay buffer
3. Mininet cleans up all OvS bridges and virtual interfaces

If Mininet leaves stale state (bridges, interfaces) from a crash:

```bash
sudo mn -c
# Cleans up all Mininet state
```

If OvS has leftover bridges:

```bash
sudo ovs-vsctl list-br | xargs -I{} sudo ovs-vsctl del-br {}
```

---

## After the Run

The following files are saved automatically:

| File | Contains |
|------|---------|
| `model_weights.pth` | Neural network weights, optimizer state, epsilon, step count |
| `/tmp/sdn_replay_buffer.pkl` | Up to 10,000 past (s, a, r, s', done) transitions |
| `/tmp/sdn_runtime_state.json` | Last state snapshot (stale after shutdown) |

---

## Repeated Runs — Accumulated Learning

Every run picks up exactly where the last one left off:

1. **Weights loaded** — `model_weights.pth` loaded at Ryu startup. Epsilon continues decaying from where it stopped.
2. **Replay buffer loaded** — `/tmp/sdn_replay_buffer.pkl` loaded. First stats cycle starts learning immediately if buffer ≥ 64 transitions.
3. **Saves every 2 s** — If the run crashes or is interrupted at any point, only the last 2-second interval is lost.

To start training from scratch:

```bash
rm -f model_weights.pth /tmp/sdn_replay_buffer.pkl
```

See also: [[Training_And_Persistence]] · [[Architecture]] · [[Troubleshooting]]
