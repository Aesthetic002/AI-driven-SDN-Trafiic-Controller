# REST API and Dashboard Reference
### Every endpoint, every panel, SSE protocol

---

## Table of Contents

- [[#Starting the API|Starting the API]]
- [[#API Endpoints|API Endpoints]]
- [[#Response Schemas|Response Schemas]]
- [[#Server-Sent Events Stream|Server-Sent Events Stream]]
- [[#Dashboard Panels|Dashboard Panels]]
- [[#Dashboard Architecture|Dashboard Architecture]]
- [[#Using the API Without a Running System|Using the API Without a Running System]]

---

## Starting the API

### During a training run

`train.py` starts the Flask API automatically as a background thread. Nothing extra to do.

### Standalone with mock data

```bash
python3 api/app.py --mock
# → http://localhost:5000
# Generates synthetic oscillating data every 2s
```

### Standalone in production mode

```bash
python3 api/app.py
# → http://localhost:5000
# Reads /tmp/sdn_runtime_state.json (written by Ryu)
# Shows zeros until Ryu starts writing the file
```

### Dashboard

```bash
# Start dashboard server
cd dashboard && python3 -m http.server 8080

# Or let train.py start it (default behaviour)
```

Open http://localhost:8080

---

## API Endpoints

### `GET /`

HTML index page with links to all endpoints. Useful as a quick sanity check.

```bash
curl http://localhost:5000/
```

---

### `GET /api/state`

Current 20-feature state vector.

```bash
curl http://localhost:5000/api/state
```

**Response:**
```json
{
  "features": {
    "link_util_s1_s3":    0.12,
    "link_util_s1_s4":    0.08,
    "link_util_s2_s3":    0.15,
    "link_util_s2_s4":    0.05,
    "link_util_s3_s5":    0.34,
    "link_util_s4_s5":    0.11,
    "link_util_crosslink": 0.00,
    "active_flows_path_a": 0.15,
    "active_flows_path_b": 0.10,
    "active_flows_path_c": 0.00,
    "packet_loss_path_a":  0.00,
    "packet_loss_path_b":  0.00,
    "jitter_path_a":       0.04,
    "jitter_path_b":       0.02,
    "bytes_path_a":        0.23,
    "bytes_path_b":        0.09,
    "time_of_day":         0.52,
    "util_trend":          0.03,
    "priority_flag":       0.0,
    "congestion_flag":     0.0
  },
  "raw": [0.12, 0.08, 0.15, 0.05, 0.34, 0.11, 0.00, 0.15, 0.10, 0.00,
          0.00, 0.00, 0.04, 0.02, 0.23, 0.09, 0.52, 0.03, 0.0, 0.0],
  "last_update": 1746613200.45
}
```

---

### `GET /api/agent`

DQN agent training state.

```bash
curl http://localhost:5000/api/agent
```

**Response:**
```json
{
  "epsilon":      0.8543,
  "learn_steps":  12,
  "total_reward": 127.45,
  "last_loss":    3.241506,
  "uptime_s":     86.3
}
```

| Field | Description |
|-------|-------------|
| `epsilon` | Current exploration rate (1.0 = 100% random, 0.01 = 1% random) |
| `learn_steps` | Number of gradient updates completed so far |
| `total_reward` | Cumulative shaped reward (not normalised by steps) |
| `last_loss` | Huber loss from the most recent gradient step |
| `uptime_s` | Seconds since the Flask API process started |

---

### `GET /api/flows`

Active flows currently tracked by the Ryu controller.

```bash
curl http://localhost:5000/api/flows
```

**Response:**
```json
{
  "10.0.0.1->10.0.0.9": {
    "action":   0,
    "path":     "PathA(s3,low-lat)",
    "age_s":    4.2,
    "priority": false
  },
  "10.0.0.3->10.0.0.9": {
    "action":   1,
    "path":     "PathB(s4,high-BW)",
    "age_s":    12.7,
    "priority": false
  }
}
```

Keys are `"src_ip->dst_ip"`. `action` is the DQN action integer (0–3). `age_s` is how long the flow has been active.

---

### `GET /api/paths`

Cumulative routing decision counters since Ryu started.

```bash
curl http://localhost:5000/api/paths
```

**Response:**
```json
{
  "PATH_A": 52,
  "PATH_B": 18,
  "PATH_C":  7,
  "DROP":    1
}
```

---

### `GET /api/metrics`

Rolling history (last 200 data points each).

```bash
curl http://localhost:5000/api/metrics
```

**Response:**
```json
{
  "reward_history": [
    {"t": 1746613000.0, "reward": 45.3},
    {"t": 1746613002.0, "reward": 46.1},
    ...
  ],
  "loss_history": [
    {"t": 1746613010.0, "loss": 4.521},
    {"t": 1746613012.0, "loss": 3.872},
    ...
  ],
  "util_history": [
    {"t": 1746613000.0, "util": 0.18},
    {"t": 1746613002.0, "util": 0.22},
    ...
  ]
}
```

`loss_history` only has entries when `last_loss` is not None (i.e., when buffer ≥ 64 transitions).

---

### `GET /api/topology`

Static network graph description. Does not change during a run.

```bash
curl http://localhost:5000/api/topology
```

**Response structure:**
```json
{
  "nodes": [
    {"id": "h_sensor1",  "ip": "10.0.0.1",  "type": "sensor",    "cluster": "A"},
    {"id": "h_camera1",  "ip": "10.0.0.3",  "type": "camera",    "cluster": "A"},
    {"id": "h_emerg",    "ip": "10.0.0.4",  "type": "emergency", "cluster": "A"},
    {"id": "s1",         "type": "switch",  "role": "access"},
    {"id": "s3",         "type": "switch",  "role": "core",      "path": "A"},
    ...
  ],
  "links": [
    {"source": "s1", "target": "s3", "bw": 20, "delay": "5ms",  "path": "A"},
    {"source": "s3", "target": "s5", "bw": 50, "delay": "2ms",  "path": "A"},
    {"source": "s3", "target": "s4", "bw": 50, "delay": "3ms",  "path": "C"},
    ...
  ]
}
```

---

### `GET /api/snapshot`

Everything in one call — combines all of the above.

```bash
curl http://localhost:5000/api/snapshot
```

Response is the full shared_state snapshot merged with the topology dict. Used by the dashboard to refresh all panels in a single SSE message.

---

### `GET /api/stream`

Server-Sent Events (SSE) stream. Pushes a full snapshot every 2 seconds.

```bash
curl -N http://localhost:5000/api/stream
```

Each event:
```
data: {"current_state": [...], "epsilon": 0.85, "learn_steps": 12, ...}

data: {"current_state": [...], "epsilon": 0.849, "learn_steps": 12, ...}
```

The dashboard uses this endpoint via `new EventSource('/api/stream')`.

---

### `POST /api/reset`

Clears the reward, loss, and utilisation history rolling buffers. Does not affect neural network weights or the replay buffer.

```bash
curl -X POST http://localhost:5000/api/reset
```

**Response:**
```json
{"status": "reset", "t": 1746613200.45}
```

Useful when starting a new experiment phase without restarting the whole system.

---

## Response Schemas

### Common timestamp fields

All `"t"` fields are Unix timestamps (seconds since epoch, float).

`"last_update"` in `/api/state` is the Unix timestamp of the last time the state vector was written. If it is more than 5 seconds old, the system may have stopped.

### Null handling

`"last_loss"` is `null` until the replay buffer reaches `BATCH_SIZE` (64 transitions). It becomes a float after the first gradient step.

---

## Server-Sent Events Stream

### Protocol

The SSE endpoint at `/api/stream` streams:

```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

Each message follows the SSE format:
```
data: <JSON string>\n\n
```

Reconnection is handled automatically by the browser's `EventSource` API. The stream does not use named events or `id:` fields — everything goes on the default `message` event.

### Connecting from JavaScript

```javascript
const es = new EventSource('http://localhost:5000/api/stream');

es.onmessage = (e) => {
    const snap = JSON.parse(e.data);
    // snap has: current_state, epsilon, learn_steps, total_reward, last_loss,
    //           path_counts, active_flows, reward_history, loss_history,
    //           util_history, last_update, uptime_s, feature_names, topology
};

es.onerror = () => {
    console.log("Disconnected from API stream");
};
```

---

## Dashboard Panels

Open http://localhost:8080 during a training run (or in mock mode).

### Top stat cards

| Card | Value | Good range |
|------|-------|-----------|
| ε (Epsilon) | Current exploration rate | < 0.5 means mostly exploiting |
| Steps | Total gradient updates | Increases ~1 per 2-4 flows × 2s |
| Reward | Cumulative shaped reward | Rising trend = learning |
| Loss | Last Huber loss | Should decrease over many sessions |
| Flows | Active flow count | 2–12 during phases 1–3 |

Cards are colour-coded: green when in a "good" range, yellow/red when at extremes.

### Connection badge

- **LIVE** (green) — SSE stream connected and receiving data
- **OFFLINE** (red) — SSE disconnected (Flask not running or network error)

### Topology diagram

D3.js force-directed graph. Nodes: switches (circles), hosts (smaller nodes labelled with hostname + IP). Links coloured by path assignment based on current `path_counts`:

```
Blue   (#4f8ef7) — Path A (S3, low-latency)
Purple (#a855f7) — Path B (S4, high-BW)
Orange (#f59e0b) — Path C (S3→S4 cross-link)
Grey            — Unused links
```

### Reward chart

Line chart, x-axis = time, y-axis = cumulative reward. Last 200 data points. Rising curve = healthy learning.

### Loss chart

Line chart of Huber loss over time. Expect high initial values (3–10), gradually decreasing. Spikes are normal — reflect exploration of new traffic patterns.

### Path decisions bar chart

Horizontal bars for PATH_A, PATH_B, PATH_C, DROP. Shows how the agent distributes flows across paths. Healthy behaviour: A and B both used, C occasional, DROP rare.

### Link utilisation bars

7 horizontal bars, one per link:
```
S1→S3   S1→S4   S2→S3   S2→S4   S3→S5   S4→S5   S3↔S4
```

All normalised 0–1. Bars turn red when > 0.8 (congestion threshold).

### Active flows table

One row per active flow:

| Source | Destination | Path | Age |
|--------|-------------|------|-----|
| 10.0.0.1 | 10.0.0.9 | PathA(s3,low-lat) | 4.2s |
| 10.0.0.3 | 10.0.0.9 | PathB(s4,high-BW) | 12.7s |

Table updates every 2 seconds. Empty between phases.

---

## Using the API Without a Running System

### Check if data is stale

```bash
python3 -c "
import json, time
with open('/tmp/sdn_runtime_state.json') as f:
    d = json.load(f)
age = time.time() - (d.get('last_update') or 0)
print(f'State is {age:.0f}s old')
print(f'Learn steps: {d[\"learn_steps\"]}')
print(f'Epsilon: {d[\"epsilon\"]}')
"
```

### Test API with mock data (no Mininet, no Ryu)

```bash
# Terminal 1
python3 api/app.py --mock

# Terminal 2
curl http://localhost:5000/api/snapshot | python3 -m json.tool

# Terminal 3 — open dashboard
cd dashboard && python3 -m http.server 8080
# → http://localhost:8080
```

See also: [[How_To_Run]] · [[Architecture]] · [[Modules_Reference]]
