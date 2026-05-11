# Essential Commands
### Every command needed to set up, run, inspect, debug, and reset the AI-SDN project

> **Important:** Any command that uses `sudo` or starts Mininet **must** be run in a **native terminal** (Konsole, xterm, etc.).
> VS Code's integrated terminal runs inside a Flatpak sandbox where `sudo` does not exist.

---

## Table of Contents

1. [One-Time Setup](#1-one-time-setup)
2. [Starting the System](#2-starting-the-system)
3. [Docker](#3-docker)
4. [Inspecting the Live System](#4-inspecting-the-live-system)
5. [API Endpoints](#5-api-endpoints)
6. [Training Diagnostics](#6-training-diagnostics)
7. [Mininet Operations](#7-mininet-operations)
8. [Open vSwitch Operations](#8-open-vswitch-operations)
9. [Component Tests and Smoke Tests](#9-component-tests-and-smoke-tests)
10. [Cleanup and Reset](#10-cleanup-and-reset)
11. [Git Operations](#11-git-operations)
12. [Process Management](#12-process-management)
13. [Quick Reference Card](#13-quick-reference-card)

---

## 1. One-Time Setup

Run these commands once after cloning the repository on a fresh machine.

### System packages (Arch / Manjaro)

```bash
sudo pacman -S --noconfirm openvswitch iperf3 net-tools iproute2 python-pip
```

If `libatomic` conflicts occur:

```bash
sudo pacman -S --overwrite "/usr/lib/libatomic*" \
               --overwrite "/usr/lib/libgcc*" \
               --overwrite "/usr/lib/libstdc*" \
               openvswitch
```

### Start Open vSwitch (required before any Mininet run)

```bash
sudo systemctl enable --now ovsdb-server ovs-vswitchd

# Verify — should print ovs_version without error
sudo ovs-vsctl show
```

### Python virtual environment

```bash
# From project root
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

### Patch Ryu for Python 3.10+

```bash
source .venv/bin/activate
python3 scripts/patch_ryu.py
# Should print: "ryu import: OK"
```

### Verify all imports

```bash
source .venv/bin/activate
python3 -c "import torch; print('torch', torch.__version__)"
python3 -c "import ryu;   print('ryu ok')"
python3 -c "import flask; print('flask', flask.__version__)"
python3 -c "import mininet; print('mininet ok')"
```

### Compile mnexec binary (if Mininet crashes with FileNotFoundError)

```bash
# Find source in AUR cache
ls ~/.cache/yay/mininet/src/mininet-*/mnexec.c

# Compile and install
gcc ~/.cache/yay/mininet/src/mininet-2.3.1b4/mnexec.c -o /tmp/mnexec
sudo cp /tmp/mnexec /usr/local/bin/mnexec
sudo chmod +x /usr/local/bin/mnexec
```

---

## 2. Starting the System

All `train.py` commands must be run with `sudo` in a native terminal.

### Standard run (4 × 60 s = 4 minutes)

```bash
sudo .venv/bin/python3 train.py --phase-secs 60
```

### Quick test run (4 × 10 s = 40 seconds)

```bash
sudo .venv/bin/python3 train.py --phase-secs 10
```

### Long training run (4 × 300 s = 20 minutes — more gradient steps)

```bash
sudo .venv/bin/python3 train.py --phase-secs 300
```

### Run without dashboard (lighter CPU)

```bash
sudo .venv/bin/python3 train.py --phase-secs 60 --no-dashboard
```

### Run with a specific baseline policy

```bash
# Available: shortest_path | ecmp_hash | round_robin | least_utilized | random
sudo .venv/bin/python3 train.py --phase-secs 60 --baseline-policy shortest_path
```

### Run in baseline-only mode (no DQN routing — for A/B comparison)

```bash
sudo .venv/bin/python3 train.py --routing-mode baseline --phase-secs 60
```

### Run with shadow comparison disabled

```bash
sudo .venv/bin/python3 train.py --phase-secs 60 --no-shadow-compare
```

### Save terminal output to a log file

```bash
sudo .venv/bin/python3 train.py --phase-secs 60 2>&1 | tee training_run.log
```

### Open dashboard in browser

```
http://localhost:8080
```

---

## 3. Docker

### Build and run (production — no live code editing)

```bash
docker compose up --build
```

### Run with live code editing (changes reflected without rebuild)

```bash
docker compose -f docker-compose.dev.yml up --build
```

### Run simulation mode (Mininet inside Docker)

```bash
docker compose -f docker-compose.sim.yml up --build
```

### Stop Docker containers

```bash
docker compose down
```

### Force rebuild (after dependency changes)

```bash
docker compose build --no-cache
docker compose up
```

### Open a shell inside the running container

```bash
docker compose exec sdn-controller bash
```

### View container logs

```bash
docker compose logs -f
```

### Check container status

```bash
docker compose ps
```

---

## 4. Inspecting the Live System

Run these in a second terminal while a training session is active.

### Watch model weights file update (updates every 2s during training)

```bash
watch -n 1 "ls -lh model_weights.pth"
```

### Watch runtime state file (raw JSON from Ryu)

```bash
watch -n 2 "python3 -m json.tool /tmp/sdn_runtime_state.json"
```

### Watch OvS flow rules on S1 (access switch — DQN installs routing rules here)

```bash
watch -n 2 "sudo ovs-ofctl dump-flows s1"
```

### Watch OvS flow rules on all switches

```bash
watch -n 2 "for sw in s1 s2 s3 s4 s5; do echo '=== '$sw; sudo ovs-ofctl dump-flows \$sw; done"
```

### Watch port statistics on S3 (core low-latency switch)

```bash
watch -n 2 "sudo ovs-ofctl dump-ports s3"
```

### Inspect saved model weights (tensor shapes and metadata)

```bash
source .venv/bin/activate
python3 - <<'EOF'
import torch, os
w = torch.load("model_weights.pth", map_location="cpu")
for k, v in w.items():
    if hasattr(v, 'shape'):
        print(f"  {k:<45} shape={str(v.shape):<25} dtype={v.dtype}")
    else:
        print(f"  {k:<45} value={v}")
print(f"\nFile size: {os.path.getsize('model_weights.pth'):,} bytes")
EOF
```

### Count parameters in the neural network

```bash
source .venv/bin/activate
python3 - <<'EOF'
import torch
w = torch.load("model_weights.pth", map_location="cpu")
online = {k[7:]: v for k,v in w.items() if k.startswith("online.")}
total = sum(v.numel() for v in online.values() if hasattr(v, 'numel'))
print(f"Online network parameters: {total:,}")
EOF
```

### Inspect replay buffer

```bash
source .venv/bin/activate
python3 - <<'EOF'
import pickle
with open("/tmp/sdn_replay_buffer.pkl", "rb") as f:
    buf = pickle.load(f)
print(f"Replay buffer size: {len(buf)} transitions")
s, a, r, ns, d = buf[0]
print(f"State shape:        {s.shape}")
print(f"Sample reward:      {r:.4f}")
print(f"Sample action:      {a}  (0=PATH_A, 1=PATH_B, 2=PATH_C, 3=DROP)")
EOF
```

---

## 5. API Endpoints

The Flask API runs at `http://localhost:5000` during a training session.

### Full snapshot (all training state)

```bash
curl -s http://localhost:5000/api/snapshot | python3 -m json.tool
```

### Agent info (epsilon, steps, episode count)

```bash
curl -s http://localhost:5000/api/agent | python3 -m json.tool
```

### Current state vector (20 features from OvS)

```bash
curl -s http://localhost:5000/api/state | python3 -m json.tool
```

### Training metrics (reward, loss history)

```bash
curl -s http://localhost:5000/api/training | python3 -m json.tool
```

### Network topology (static graph data)

```bash
curl -s http://localhost:5000/api/topology | python3 -m json.tool
```

### Path counts (PATH_A / PATH_B / PATH_C / DROP)

```bash
curl -s http://localhost:5000/api/snapshot | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['path_counts'])"
```

### SSE stream (real-time updates — Ctrl-C to stop)

```bash
curl -N http://localhost:5000/api/stream
```

### Start Flask in mock mode (no Mininet needed — for dashboard testing)

```bash
source .venv/bin/activate
python3 api/app.py --mock
```

---

## 6. Training Diagnostics

### Run DQN agent smoke test (no Mininet, no Ryu)

```bash
source .venv/bin/activate
python3 agent/dqn_agent.py
# Output: epsilon, steps, loss, save/load verification
```

### Test reward computation for a specific action

```bash
source .venv/bin/activate
python3 - <<'EOF'
from agent.dqn_agent import compute_reward_components

# Simulate a moderate-load state
state = [0.3]*20
next_state = [0.3]*20
next_state[4]  = 0.6   # util_s3_s5 = 60%
next_state[5]  = 0.2   # util_s4_s5 = 20%
next_state[10] = 0.01  # packet_loss_path_a = 1%
next_state[14] = 0.5   # bytes_path_a
next_state[18] = 0.0   # priority_flag off
next_state[19] = 0.0   # congestion_flag off

for action in range(4):
    comp = compute_reward_components(state, action, next_state)
    print(f"Action {action}: total={comp['total']:.4f}  "
          f"lat={comp['latency']:.3f}  rel={comp['reliability']:.3f}  "
          f"thr={comp['throughput']:.3f}  fair={comp['fairness']:.3f}")
EOF
```

### Check epsilon and step count without starting a full run

```bash
source .venv/bin/activate
python3 - <<'EOF'
import torch
w = torch.load("model_weights.pth", map_location="cpu")
print(f"Epsilon:       {w['epsilon']:.6f}")
print(f"Learn steps:   {w['steps']}")
print(f"Episode count: {w.get('episode_count', 'N/A')}")
EOF
```

### Run stats collector with synthetic data (no Mininet)

```bash
source .venv/bin/activate
python3 collector/stats_collector.py --mock --once
```

### Run stats collector in continuous mock mode

```bash
source .venv/bin/activate
python3 collector/stats_collector.py --mock
```

### View training summary from last run

```bash
python3 -m json.tool /tmp/sdn_runtime_state.json | grep -E '"(epsilon|learn_steps|total_reward|last_loss|path_counts|episode_count)"'
```

---

## 7. Mininet Operations

All Mininet commands require `sudo`.

### Test topology connectivity (standalone — no Ryu needed)

```bash
sudo .venv/bin/python3 mininet/iot_topology.py --test
# Expected: "0% dropped (90/90 received)" after 35s STP convergence
```

### Open Mininet interactive CLI

```bash
# Requires Ryu to be running first
sudo .venv/bin/python3 mininet/iot_topology.py --cli
```

### Common commands inside the Mininet CLI

```
mininet> pingall                         # connectivity test
mininet> h_sensor1 ping -c 3 10.0.0.9   # ping from sensor to server
mininet> h_camera1 iperf3 -c 10.0.0.9 -b 8M -t 10   # generate 8 Mbps traffic
mininet> h_emerg iperf3 -c 10.0.0.9 -b 1M -t 5      # emergency flow
mininet> xterm h_sensor1                 # open xterm for a specific host
mininet> sh sudo ovs-ofctl dump-flows s1  # show flow table from within CLI
mininet> exit
```

### Saturate the S1→S3 link (for congestion testing)

```
mininet> h_camera1 iperf3 -c 10.0.0.9 -b 18M -t 30 &
```

The S1→S3 link is 20 Mbps. 18M will bring `link_util_s1_s3` (state[0]) near 0.9 and trigger rerouting.

---

## 8. Open vSwitch Operations

### Check OvS is running

```bash
sudo ovs-vsctl show
```

### List all bridges (should be empty when Mininet is not running)

```bash
sudo ovs-vsctl list-br
```

### Show flow tables on a specific switch

```bash
sudo ovs-ofctl dump-flows s1   # access switch A
sudo ovs-ofctl dump-flows s2   # access switch B
sudo ovs-ofctl dump-flows s3   # core low-latency
sudo ovs-ofctl dump-flows s4   # core high-BW
sudo ovs-ofctl dump-flows s5   # aggregation/server
```

### Show port statistics

```bash
sudo ovs-ofctl dump-ports s3   # TX/RX bytes and packets per port
```

### Show port descriptions (port numbers and names)

```bash
sudo ovs-ofctl show s1
```

### Delete all flows on a switch (force re-learning)

```bash
sudo ovs-ofctl del-flows s1
```

### Delete all Mininet bridges manually (if `mn -c` fails)

```bash
sudo ovs-vsctl list-br | xargs -r -I{} sudo ovs-vsctl del-br {}
```

---

## 9. Component Tests and Smoke Tests

### Test the entire stack without Mininet (mock API + dashboard)

```bash
# Terminal 1
source .venv/bin/activate
python3 api/app.py --mock

# Terminal 2
cd dashboard && python3 -m http.server 8080

# Open http://localhost:8080 — all panels animate with synthetic data
```

### Start Ryu controller only (for manual Mininet or external switches)

```bash
source .venv/bin/activate
python3 -m ryu.cmd.manager \
    --ofp-tcp-listen-port 6633 \
    controller/ryu_controller.py
```

### Start dashboard only (static file server)

```bash
cd dashboard && python3 -m http.server 8080
```

Or from project root:

```bash
python3 -c "
import http.server, functools, os
h = functools.partial(http.server.SimpleHTTPRequestHandler, directory='dashboard')
http.server.HTTPServer(('', 8080), h).serve_forever()
"
```

### Run baseline router standalone test

```bash
source .venv/bin/activate
python3 - <<'EOF'
from controller.baseline_router import BaselineRouter
router = BaselineRouter(policy="least_utilized", seed=42)
state = [0.1, 0.8, 0.1, 0.8, 0.2, 0.3, 0.1] + [0.0]*13
action = router.select_action(state, flow_key=("10.0.0.1","10.0.0.9"))
print(f"Baseline chose action: {action}  (0=PATH_A, 1=PATH_B, 2=PATH_C, 3=DROP)")
EOF
```

---

## 10. Cleanup and Reset

### Stop a running session

Press `Ctrl-C` in the terminal running `train.py`. The signal handler terminates Ryu, which saves final weights before exiting.

### Full clean slate (after any crash)

```bash
# Kill leftover processes
sudo pkill -f "ryu.cmd.manager"
sudo pkill -f "iot_topology"
sudo pkill -f "scenario_runner"
sudo pkill -f "api/app.py"

# Clean Mininet state
sudo mn -c

# Verify OvS is clean
sudo ovs-vsctl show

# Remove runtime files
rm -f /tmp/sdn_runtime_state.json /tmp/sdn_replay_buffer.pkl
```

### Reset training only (keep environment clean)

```bash
rm -f model_weights.pth /tmp/sdn_replay_buffer.pkl
```

### Reset training completely including runtime state

```bash
rm -f model_weights.pth /tmp/sdn_replay_buffer.pkl /tmp/sdn_runtime_state.json
```

### Free a specific port if still in use

```bash
# Find what's using port 5000
sudo lsof -i :5000

# Kill it (replace PID with actual)
kill -9 <PID>

# One-liner
sudo lsof -ti :5000 | xargs -r kill -9
sudo lsof -ti :8080 | xargs -r kill -9
sudo lsof -ti :6633 | xargs -r kill -9
```

### Remove all Python cache files

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete 2>/dev/null
```

### Remove all temporary files

```bash
rm -f /tmp/sdn_runtime_state.json /tmp/sdn_replay_buffer.pkl /tmp/dqn_test.pt
```

---

## 11. Git Operations

### Check status

```bash
git status
git diff
```

### Stage and commit

```bash
git add agent/dqn_agent.py controller/ryu_controller.py api/app.py api/shared_state.py
git add dashboard/comparison.html dashboard/shared.js dashboard/styles.css
git add train.py
git commit -m "Your commit message"
```

### Push to remote

```bash
git push origin main
```

### Pull latest changes from remote

```bash
git pull origin main
```

### View recent commits with changed files

```bash
git log --stat -5
```

### View commit history one-line

```bash
git log --oneline -20
```

### Undo last commit (keep changes staged)

```bash
git reset --soft HEAD~1
```

---

## 12. Process Management

### Check what's running

```bash
pgrep -a python3
# Look for: ryu.cmd.manager, iot_topology, api/app.py, scenario_runner, train.py
```

### Check what's listening on key ports

```bash
sudo ss -tlnp | grep -E "5000|6633|8080"
```

### Kill all project processes

```bash
sudo pkill -f "ryu.cmd.manager"
sudo pkill -f "train.py"
sudo pkill -f "iot_topology"
sudo pkill -f "scenario_runner"
sudo pkill -f "api/app.py"
```

### Check OvS services

```bash
sudo systemctl status ovsdb-server ovs-vswitchd
```

### Restart OvS services

```bash
sudo systemctl restart ovsdb-server ovs-vswitchd
```

---

## 13. Quick Reference Card

| Goal | Command |
|---|---|
| Setup (first time) | `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python3 scripts/patch_ryu.py` |
| Start OvS | `sudo systemctl start ovsdb-server ovs-vswitchd` |
| Full training run | `sudo .venv/bin/python3 train.py --phase-secs 60` |
| Quick test (40s) | `sudo .venv/bin/python3 train.py --phase-secs 10` |
| Dashboard only | `cd dashboard && python3 -m http.server 8080` |
| Mock mode (no Mininet) | `python3 api/app.py --mock` |
| View snapshot | `curl -s http://localhost:5000/api/snapshot \| python3 -m json.tool` |
| Watch flow tables | `watch -n 2 "sudo ovs-ofctl dump-flows s1"` |
| Inspect weights | `python3 -c "import torch; [print(k,v.shape) for k,v in torch.load('model_weights.pth').items() if hasattr(v,'shape')]"` |
| Check epsilon | `python3 -c "import torch; w=torch.load('model_weights.pth'); print(w['epsilon'], w['steps'])"` |
| Connectivity test | `sudo .venv/bin/python3 mininet/iot_topology.py --test` |
| Clean crash state | `sudo mn -c && sudo pkill -f ryu.cmd.manager` |
| Reset training | `rm -f model_weights.pth /tmp/sdn_replay_buffer.pkl` |
| Full cleanup | `sudo mn -c && sudo pkill -f "ryu\|iot_topology\|train.py" && sudo lsof -ti :5000 :6633 :8080 \| xargs -r kill -9` |
| Open Mininet CLI | `sudo .venv/bin/python3 mininet/iot_topology.py --cli` |
| Agent smoke test | `python3 agent/dqn_agent.py` |

---

See also: [How_To_Run](../phase%203%20-%20Implementation/How_To_Run.md) · [Troubleshooting](../phase%203%20-%20Implementation/Troubleshooting.md) · [Architecture](../phase%203%20-%20Implementation/Architecture.md)
