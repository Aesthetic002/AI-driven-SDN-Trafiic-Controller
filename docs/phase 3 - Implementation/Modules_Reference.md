# Modules Reference
### Every Python file documented — purpose, public API, key internals

---

## Table of Contents

- [[#constants.py|constants.py]]
- [[#mininet/iot_topology.py|mininet/iot_topology.py]]
- [[#collector/stats_collector.py|collector/stats_collector.py]]
- [[#agent/dqn_agent.py|agent/dqn_agent.py]]
- [[#controller/ryu_controller.py|controller/ryu_controller.py]]
- [[#traffic/generators.py|traffic/generators.py]]
- [[#traffic/scenario_runner.py|traffic/scenario_runner.py]]
- [[#api/app.py|api/app.py]]
- [[#api/shared_state.py|api/shared_state.py]]
- [[#dashboard/index.html|dashboard/index.html]]
- [[#train.py|train.py]]
- [[#scripts/patch_ryu.py|scripts/patch_ryu.py]]

---

## constants.py

**Role:** Single source of truth for the entire project. Every other file imports from here — nothing is hard-coded elsewhere.

### Sections

| Section | Constants |
|---------|-----------|
| Controller | `CONTROLLER_HOST`, `CONTROLLER_PORT` |
| Switch names | `SWITCHES` list |
| Port assignments | `S1_PORT_*`, `S2_PORT_*`, `S3_PORT_*`, `S4_PORT_*`, `S5_PORT_*` |
| Link capacities (Mbps) | `LINK_BW_SENSOR`, `LINK_BW_CAMERA`, `LINK_BW_ACCESS_CORE`, `LINK_BW_CORE_SERVER_A/B`, `LINK_BW_CROSSLINK`, `LINK_BW_SERVER` |
| Link delays | `LINK_DELAY_*` — all strings like `"5ms"` |
| Host IPs | `IP_SENSOR1`–`IP_SERVER2`, cluster sets `CLUSTER_A_IPS`, `CLUSTER_B_IPS` |
| Traffic classification | `SENSOR_PORT=5005`, `VIDEO_PORT=5006`, `ELEPHANT_PORT=5007`, `ACTUATOR_PORT=5008` |
| DSCP values | `DSCP_EMERGENCY=46`, `DSCP_SENSOR=34`, `DSCP_VIDEO=26`, `DSCP_ELEPHANT=0` |
| DQN actions | `ACTION_PATH_A=0`, `ACTION_PATH_B=1`, `ACTION_PATH_C=2`, `ACTION_DROP=3`, `NUM_ACTIONS=4`, `ACTION_NAMES` dict |
| State vector | `STATE_FEATURES` list of (idx, name, source, normalisation) tuples; `STATE_DIM=20`; `FEATURE_NAMES` |
| Training hyperparams | `SEQUENCE_LEN=10`, `REPLAY_CAPACITY=10_000`, `BATCH_SIZE=64`, `GAMMA=0.99`, `LR=1e-4`, `EPS_START/END/DECAY`, `TARGET_SYNC=100`, `GRAD_CLIP_NORM=1.0`, `STATS_INTERVAL=2.0` |
| Reward weights | `R_LATENCY=0.4`, `R_RELIABILITY=0.3`, `R_THROUGHPUT=0.2`, `R_FAIRNESS=0.1`, `R_PRIORITY_MUL=5.0` |
| API | `API_HOST`, `API_PORT=5000`, `DASHBOARD_PORT=8080` |
| Runtime files | `RUNTIME_STATE_FILE="/tmp/sdn_runtime_state.json"`, `REPLAY_BUFFER_FILE="/tmp/sdn_replay_buffer.pkl"` |

### Important derivation

```python
STATE_DIM     = len(STATE_FEATURES)   # always 20
FEATURE_NAMES = [f[1] for f in STATE_FEATURES]
```

---

## mininet/iot_topology.py

**Role:** Defines and starts the virtual IoT network topology using Mininet + Open vSwitch.

### Classes

**`IoTTopo(Topo)`**

Builds the 2-tier network in `build()`. Port assignment is determined by `addLink()` call order — do not reorder links without updating `constants.py`.

```
Port order per switch:
  S1: addLink order = sensor1, sensor2, camera1, emerg, →s3, →s4
      → ports               1       2        3      4     5    6
  S2: sensor3, sensor4, camera2, actuator, →s3, →s4
  S3: ←s1, ←s2, →s5, ↔s4
  S4: ←s1, ←s2, →s5, ↔s3
  S5: ←s3, ←s4, server1, server2
```

All links created with `TCLink` — rate-limiting and delay emulation via Linux `tc htb`.

### Functions

**`build_net(use_remote_controller: bool) → Mininet`**

- `True` — uses `RemoteController` (Ryu at `CONTROLLER_HOST:CONTROLLER_PORT`), `failMode="secure"`
- `False` — uses built-in `OVSController` (learning switch), `failMode="standalone"`, `stp=True`

**`run(args)`** — CLI handler: starts network, optional `--test` (pingall) or `--cli` (interactive).

### Direct usage

```bash
# Connectivity test (standalone, waits 35s for STP)
sudo .venv/bin/python3 mininet/iot_topology.py --test

# Interactive CLI (needs Ryu running first for non-trivial testing)
sudo .venv/bin/python3 mininet/iot_topology.py --cli

# Standalone keep-alive (Ryu connects automatically)
sudo .venv/bin/python3 mininet/iot_topology.py
```

---

## collector/stats_collector.py

**Role:** Polls all 5 OvS switches every `STATS_INTERVAL` seconds and computes the 20-float state vector consumed by the DQN agent.

### Class: `StatsCollector`

**`get_state() → list[float]`** — main entry point, calls `ovs-ofctl dump-ports` and `ovs-ofctl dump-flows` on all switches, then calls `_compute()`.

**`get_state_dict() → dict`** — same as `get_state()` but keyed by `FEATURE_NAMES`.

Internal state tracked between calls:
- `_prev` — previous `PortStats` snapshot for delta computation
- `_prev_time` — timestamp of previous call
- `_prev_avg_util` — for utilisation trend feature
- `_jitter_hist` — rolling 10-sample utilisation history per path (for jitter estimate)

### Key parsers

**`parse_port_stats(raw: str) → PortStats`**

Parses `ovs-ofctl dump-ports` output. Returns `{port_no: {rx_bytes, tx_bytes, rx_pkts, tx_pkts, rx_drop, tx_drop}}`.

**`parse_flow_stats(raw: str) → list[dict]`**

Parses `ovs-ofctl dump-flows` output. Returns list of `{out_port, n_packets, n_bytes, duration, priority, dscp}`.

### Module-level singleton

```python
_collector = StatsCollector()

def get_state() -> list[float]:
    return _mock_state() if _mock_mode else _collector.get_state()
```

All callers use `get_state()` — they never instantiate `StatsCollector` directly.

### Standalone usage

```bash
# Live (needs Mininet running)
python3 collector/stats_collector.py

# Synthetic (no Mininet)
python3 collector/stats_collector.py --mock

# One snapshot
python3 collector/stats_collector.py --mock --once

# Custom interval
python3 collector/stats_collector.py --mock --interval 0.5
```

---

## agent/dqn_agent.py

**Role:** The entire learning stack — neural network, replay buffer, action selection, gradient updates, persistence.

### Class: `DuelingLSTM(nn.Module)`

Architecture:
```
Input (batch, seq_len=10, state_dim=20)
  └─► LSTM (hidden=128, 2 layers, dropout=0.2)
        └─► last time-step hidden state (batch, 128)
              ├─► Value head:     Linear(128,64) → ReLU → Linear(64,1)   → V(s)
              └─► Advantage head: Linear(128,64) → ReLU → Linear(64,4)   → A(s,a)
                                                  Q = V + (A - mean(A))
```

**`forward(x) → Q-values (batch, 4)`**

### Class: `ReplayBuffer`

Fixed-capacity deque (`maxlen=REPLAY_CAPACITY`). Each entry: `(state_seq, action, reward, next_state_seq, done)` as numpy arrays.

**`push(state_seq, action, reward, next_state_seq, done)`** — appends one transition.

**`sample(batch_size) → (states, actions, rewards, next_states, dones)`** — random batch as PyTorch tensors.

### Function: `compute_reward(state, action, next_state) → float`

See [[State_And_Reward]] for the full reward formula. Returns a float clipped to `[-1.0, 5.0]`.

### Class: `DQNAgent`

**`select_action(state_seq: list[list[float]]) → int`**

Epsilon-greedy: with probability `epsilon` returns a random action; otherwise runs the online network forward and returns `argmax(Q)`.

**`store(state_seq, action, reward, next_state_seq, done)`**

Pushes one transition to the replay buffer.

**`learn() → float | None`**

Returns `None` if buffer has fewer than `BATCH_SIZE` transitions. Otherwise:
1. Sample batch of 64 transitions
2. Double-DQN: online net selects next action, target net evaluates it
3. Bellman target: `r + γ * Q_target(s', argmax_online(s')) * (1 - done)`
4. Loss: Smooth L1 (Huber) between current Q and target
5. Adam optimizer step, gradient clipped to norm 1.0
6. Decay epsilon: `epsilon = max(EPS_END, epsilon * EPS_DECAY)`
7. Every `TARGET_SYNC=100` steps: sync target network

**`save(path)` / `load(path)`**

Saves/loads: `online` weights, `target` weights, `optimizer` state, `epsilon`, `steps`.

**`save_buffer(path)` / `load_buffer(path)`**

Persists the replay buffer via `pickle`. Uses atomic write (write to `.tmp` then `os.replace()`) to prevent corruption on crash.

---

## controller/ryu_controller.py

**Role:** The Ryu SDN application — handles OpenFlow events, drives the training loop, bridges to Flask.

### Class: `IoTController(app_manager.RyuApp)`

**Startup (`__init__`)**

1. Creates `DQNAgent()`, loads `model_weights.pth` if it exists
2. Loads `/tmp/sdn_replay_buffer.pkl` if it exists (restores past experiences)
3. Creates `StatsCollector()`
4. Spawns `_stats_loop` greenlet via `hub.spawn()`
5. Initialises `state_buffer` (deque of 10 state snapshots)
6. Initialises `flow_table: dict[(src_ip, dst_ip), FlowEntry]`
7. Initialises `path_counts: dict[int, int]` and `datapaths: dict[int, Datapath]`

**`switch_features_handler`** (CONFIG_DISPATCHER)

Called once per switch connection. Installs table-miss rule (send-to-controller) on every switch. Installs static server-distribution rules on S5 (one rule per server IP).

**`packet_in_handler`** (MAIN_DISPATCHER)

Called for every PacketIn (new flow). Steps:
1. Parse Ethernet → IPv4 headers
2. Determine if flow is IoT→server (forward) or server→IoT (return)
3. For return flows: install hardcoded return path via S3 (no DQN)
4. For forward flows: check `flow_table` — if new, call `agent.select_action(state_seq)`
5. Install FlowMod rules on all hops of the chosen path
6. Send PacketOut to forward the triggering packet immediately
7. Record flow in `flow_table` with action, timestamp, priority flag

**`flow_removed_handler`** (MAIN_DISPATCHER)

Called when a flow times out. Removes the flow from `flow_table`. Stores final transition with `done=True` in the replay buffer.

**`_stats_loop`** (greenlet, runs every 2 s)

The training heartbeat:
```
while True:
    hub.sleep(STATS_INTERVAL)           # 2 seconds
    new_state = collector.get_state()   # poll OvS
    _patch_state(new_state)             # overwrite flow-count features
    state_buffer.append(new_state)      # rolling window

    for each active flow:
        reward = compute_reward(...)
        agent.store(...)

    loss = agent.learn()                # one gradient step
    agent.save(WEIGHTS_PATH)           # save every cycle
    agent.save_buffer(REPLAY_BUFFER_FILE)

    _write_state_file(new_state, loss)  # JSON for Flask
    shared_state.push_*(...)            # in-process Flask update
```

**`_install_table_miss(dp)`**

Installs priority-0 flow: match=* → send to controller. Required so PacketIn fires for unknown flows.

**`_install_s5_static(dp)`**

Installs static rules on S5: `match(ip_dst=IP_SERVER1) → output(port=3)` and `match(ip_dst=IP_SERVER2) → output(port=4)`. These never need to change.

**`_install_path(src_ip, dst_ip, action, is_priority)`**

Installs FlowMod rules for a forward flow on every switch along the chosen path. Priority is `PRIO_EMERGENCY=200` for emergency/actuator flows, `PRIO_FLOW=100` for normal flows.

Path routing:
```
ACTION_PATH_A (0): S1/S2 port→5 (→S3), S3 port→3 (→S5)
ACTION_PATH_B (1): S1/S2 port→6 (→S4), S4 port→3 (→S5)
ACTION_PATH_C (2): S1/S2 port→5 (→S3), S3 port→4 (→S4), S4 port→3 (→S5)
ACTION_DROP   (3): OFPP_DROP (packets silently discarded)
```

**`close()`**

Called by Ryu on shutdown. Saves final weights and replay buffer, logs buffer size.

### Internal constants

```python
WEIGHTS_PATH = <project_root>/model_weights.pth
DPID_S1..S5  = 1..5  (Mininet assigns 1-indexed datapath IDs)
FLOW_IDLE    = 10    # seconds idle before FlowRemoved
FLOW_HARD    = 60    # hard timeout regardless of traffic
PRIO_TABLE_MISS = 0
PRIO_STATIC     = 10
PRIO_FLOW       = 100
PRIO_EMERGENCY  = 200
```

---

## traffic/generators.py

**Role:** Standalone traffic generator processes that run inside Mininet host network namespaces via `host.popen()`.

### Modes

| Mode | Protocol | DSCP | Rate | Use |
|------|----------|------|------|-----|
| `server-udp` | UDP server | — | receive-only | Runs on h_server1/2 |
| `server-tcp` | TCP server | — | receive-only | Runs on h_server1/2 |
| `sensor` | UDP | AF41 (34) | 1 pkt/s, 100 bytes | Simulates IoT sensor reading |
| `video` | UDP | AF31 (26) | configurable Mbps, 1400 B packets | Camera feed |
| `elephant` | TCP | BE (0) | as fast as possible | Bulk data transfer |
| `emergency` | UDP | EF (46) | 10 pkt/s, 50 bytes | Emergency alert |
| `actuator` | UDP | EF (46) | 5 pkt/s, 20 bytes | Control command |

### DSCP marking

```python
tos = dscp << 2   # DSCP occupies top 6 bits of the TOS byte
sock.setsockopt(IPPROTO_IP, IP_TOS, tos)
```

### Packet payloads

- **Sensor:** `struct.pack("!IId", seq, timestamp, reading)` padded to 100 bytes
- **Video:** `seq + timestamp_ms` padded with repeated byte to 1400 bytes
- **Emergency:** `struct.pack("!II?", seq, timestamp, True)` + `"EMERGENCY"` literal
- **Actuator:** `struct.pack("!IId", seq, timestamp, setpoint=75.0)`
- **Elephant:** `b"\xAB" * 65536` chunks

### CLI usage

```bash
python3 traffic/generators.py server-udp --port 5005
python3 traffic/generators.py sensor     --dst 10.0.0.9 --duration 60
python3 traffic/generators.py video      --dst 10.0.0.9 --duration 60 --mbps 5
python3 traffic/generators.py elephant   --dst 10.0.0.9 --mb 200
python3 traffic/generators.py emergency  --dst 10.0.0.9 --duration 60
python3 traffic/generators.py actuator   --dst 10.0.0.9 --duration 60
```

---

## traffic/scenario_runner.py

**Role:** Orchestrates the 4-phase traffic scenario on a running Mininet network.

### Class: `ScenarioRunner`

**`__init__(net, phase_secs=60)`** — takes a running `Mininet` object.

**`run()`** — starts servers, then iterates through 4 phases sequentially. Blocks until all phases complete or `KeyboardInterrupt`.

**`stop_all()`** — sends SIGINT to all spawned processes, waits for them to exit.

### 4-Phase Traffic Plan

| Phase | Time | Traffic added |
|-------|------|--------------|
| 1 | 0–60s | 4 sensors (h_sensor1–4 → server1/2, UDP, 1 pkt/s) |
| 2 | 60–120s | +2 cameras (h_camera1, h_camera2, 5 Mbps UDP) |
| 3 | 120–180s | +elephant TCP 150 MB (h_camera1) + emergency 60s (h_emerg) + actuator 60s (h_actuator) |
| 4 | 180–240s | Recovery — light 2 Mbps video only (h_camera1) |

All phase 1 sensors run for the full 240s (started with `--duration 240`). Camera video streams from phase 2 run for 180s. Phase-specific flows are added on top.

### Server setup

Before phase 1 starts, `_start_servers()` starts UDP and TCP servers on both h_server1 and h_server2:

```
h_server1: server-udp :5005, server-udp :5006, server-tcp :5007, server-udp :5008
h_server2: same
```

---

## api/app.py

**Role:** Flask REST API exposing the DQN agent's live state. Can run in mock mode (no Ryu needed) or production mode (reads Ryu's JSON file).

### Endpoints

| Method | Path | Returns |
|--------|------|---------|
| GET | `/` | HTML index page with links to all endpoints |
| GET | `/api/state` | Current 20-feature vector with names + raw list |
| GET | `/api/agent` | epsilon, learn_steps, total_reward, last_loss, uptime_s |
| GET | `/api/flows` | Active flows dict |
| GET | `/api/paths` | Path decision counters {PATH_A, PATH_B, PATH_C, DROP} |
| GET | `/api/metrics` | reward_history, loss_history, util_history (last 200 each) |
| GET | `/api/topology` | Static network graph (nodes + links) |
| GET | `/api/snapshot` | Everything in one call (all of the above merged) |
| GET | `/api/stream` | Server-Sent Events stream, pushes snapshot every 2s |
| POST | `/api/reset` | Clears reward/loss/util history |

### Operating modes

**Mock mode** (`--mock` flag):
- Runs `_mock_pump()` in a background thread
- Generates synthetic oscillating utilisation data every 2s
- No Mininet, no Ryu needed — useful for dashboard development

**Production mode** (default):
- Runs `_file_pump()` in a background thread
- Polls `RUNTIME_STATE_FILE` (`/tmp/sdn_runtime_state.json`) every 1s
- Detects changes by comparing file mtime

### Entry points

```bash
# Mock (development)
python3 api/app.py --mock

# Production (alongside Ryu)
python3 api/app.py

# Custom host/port
python3 api/app.py --host 0.0.0.0 --port 5000
```

---

## api/shared_state.py

**Role:** Thread-safe in-memory bridge between the Ryu controller and the Flask API within the same process.

### Module-level state

```python
_state = {
    "current_state":  [0.0] * 20,
    "feature_names":  [],
    "epsilon":        1.0,
    "learn_steps":    0,
    "total_reward":   0.0,
    "last_loss":      None,
    "path_counts":    {"PATH_A": 0, "PATH_B": 0, "PATH_C": 0, "DROP": 0},
    "active_flows":   {},
    "reward_history": deque(maxlen=200),
    "loss_history":   deque(maxlen=200),
    "util_history":   deque(maxlen=200),
    "last_update":    None,
    "start_time":     time.time(),
}
```

### Write API (called by Ryu / file_pump)

- `push_state(feature_vector, feature_names)` — updates state + last_update
- `push_agent(epsilon, learn_steps, total_reward, loss)` — appends to reward_history and loss_history
- `push_path_counts(counts: dict[int, int])` — translates action IDs to string keys
- `push_flows(flow_table: dict)` — converts FlowEntry objects to serialisable dicts
- `push_util(avg_util: float)` — appends to util_history

### Read API (called by Flask)

**`snapshot() → dict`** — returns a complete JSON-serialisable deep copy. All floats rounded, deques converted to lists.

---

## dashboard/index.html

**Role:** Single-page D3.js dashboard. Connects to the Flask SSE stream and renders live network state.

### SSE connection

```javascript
const es = new EventSource('http://localhost:5000/api/stream');
es.onmessage = (e) => {
    const snap = JSON.parse(e.data);
    updateAll(snap);
};
```

Updates every 2 seconds. Shows "LIVE" badge when connected, "OFFLINE" badge on error.

### Panels

| Panel | Data source | Visualisation |
|-------|------------|--------------|
| Epsilon | `snap.epsilon` | Stat card (green when < 0.1) |
| Learn Steps | `snap.learn_steps` | Stat card |
| Total Reward | `snap.total_reward` | Stat card |
| Last Loss | `snap.last_loss` | Stat card |
| Flow Count | `Object.keys(snap.active_flows).length` | Stat card |
| Topology | `snap.topology` + `snap.path_counts` | D3 force-directed graph |
| Reward chart | `snap.reward_history` | SVG line chart, last 200 points |
| Loss chart | `snap.loss_history` | SVG line chart |
| Path decisions | `snap.path_counts` | Horizontal bar chart, colour-coded |
| Link utilisation | `snap.current_state[0..6]` | Horizontal bar chart, 7 links |
| Active flows | `snap.active_flows` | HTML table: src, dst, path, age |

### Colour scheme

- Path A (low-latency): blue `#4f8ef7`
- Path B (high-BW): purple `#a855f7`
- Path C (cross-link): orange `#f59e0b`
- Drop: red `#ef4444`
- Background: `#0f1117` (dark)

---

## train.py

**Role:** Single-command orchestrator. Starts all five components in the correct order, runs the full training scenario, prints a summary, and shuts down cleanly.

### Start order

```
1. Ryu subprocess  (python3 -m ryu.cmd.manager controller/ryu_controller.py)
2. _stream_output thread  (pipes Ryu stdout → terminal with [ryu] prefix)
3. Wait for :6633 (up to 30 retries × 1s)
4. Flask API thread  (api.app.run)
5. _file_pump thread  (polls RUNTIME_STATE_FILE)
6. Wait for :5000 (up to 10 retries)
7. Dashboard HTTP thread  (SimpleHTTPRequestHandler on :8080)
8. start_mininet()  — builds topology, starts traffic scenario, BLOCKS
9. Print summary from RUNTIME_STATE_FILE
10. cleanup() → terminate Ryu, sys.exit
```

### Cleanup

`cleanup()` is registered as SIGINT and SIGTERM handler. It calls `proc.terminate()` on all subprocesses, waits up to 3s, then `proc.kill()` if needed.

### Mininet import workaround

```python
sys.path.insert(0, os.path.join(ROOT, "mininet"))
from iot_topology import build_net
```

This is necessary because Python would otherwise resolve `mininet.iot_topology` as a submodule of the pip-installed `mininet` package, not the project's own `mininet/` folder.

---

## scripts/patch_ryu.py

**Role:** Makes Ryu 4.34 compatible with Python 3.10+. Run once after installing Ryu.

### What it patches

**All `.py` files in the ryu package:**

| Old | New |
|-----|-----|
| `collections.Callable` | `collections.abc.Callable` |
| `collections.Iterable` | `collections.abc.Iterable` |
| `collections.Iterator` | `collections.abc.Iterator` |
| `collections.Mapping` | `collections.abc.Mapping` |
| `collections.MutableMapping` | `collections.abc.MutableMapping` |
| `collections.MutableSequence` | `collections.abc.MutableSequence` |
| `collections.Sequence` | `collections.abc.Sequence` |
| `collections.Set` | `collections.abc.Set` |
| `collections.MutableSet` | `collections.abc.MutableSet` |
| `collections.Generator` | `collections.abc.Generator` |
| `collections.Coroutine` | `collections.abc.Coroutine` |
| `collections.Awaitable` | `collections.abc.Awaitable` |

**`ryu/app/wsgi.py` specifically:**

```python
# Before (raises ImportError on eventlet >= 0.33.0):
from eventlet.wsgi import ALREADY_HANDLED

# After:
try:
    from eventlet.wsgi import ALREADY_HANDLED as _ALREADY_HANDLED
except ImportError:
    _ALREADY_HANDLED = []
```

### Usage

```bash
python3 scripts/patch_ryu.py
# Prints list of patched files, then "ryu import: OK"
```

Safe to run multiple times — already-patched files are skipped.

See also: [[How_To_Run]] · [[Architecture]] · [[Troubleshooting]]
