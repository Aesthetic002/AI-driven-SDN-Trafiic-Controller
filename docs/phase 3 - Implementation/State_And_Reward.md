# State Vector and Reward Function
### The 20 features the DQN observes and how rewards are shaped

---

## Table of Contents

- [[#The 20-Feature State Vector|The 20-Feature State Vector]]
- [[#Feature Details|Feature Details]]
- [[#How the State is Built|How the State is Built]]
- [[#The LSTM Sequence|The LSTM Sequence]]
- [[#Reward Function|Reward Function]]
- [[#Reward Components|Reward Components]]
- [[#Priority Multiplier|Priority Multiplier]]
- [[#Drop Action Reward|Drop Action Reward]]
- [[#Reward Clipping|Reward Clipping]]
- [[#Example Reward Calculations|Example Reward Calculations]]

---

## The 20-Feature State Vector

The state is a flat list of 20 normalised floats. All values are in `[0, 1]` except `util_trend` which spans `[-1, 1]`.

| Index | Name | Source | Normalisation |
|-------|------|--------|--------------|
| 0 | `link_util_s1_s3` | S1 port 5 TX bytes delta | Mbps / 20.0 (link cap) |
| 1 | `link_util_s1_s4` | S1 port 6 TX bytes delta | Mbps / 20.0 |
| 2 | `link_util_s2_s3` | S2 port 5 TX bytes delta | Mbps / 20.0 |
| 3 | `link_util_s2_s4` | S2 port 6 TX bytes delta | Mbps / 20.0 |
| 4 | `link_util_s3_s5` | S3 port 3 TX bytes delta | Mbps / 50.0 (S3→S5 cap) |
| 5 | `link_util_s4_s5` | S4 port 3 TX bytes delta | Mbps / 100.0 (S4→S5 cap) |
| 6 | `link_util_crosslink` | S3 port 4 TX bytes delta | Mbps / 50.0 |
| 7 | `active_flows_path_a` | Flow count on S3 port→S5 | count / 20.0 |
| 8 | `active_flows_path_b` | Flow count on S4 port→S5 | count / 20.0 |
| 9 | `active_flows_path_c` | Flow count on S3 port→S4 | count / 20.0 |
| 10 | `packet_loss_path_a` | Drop count / total packets on S3 port 3 | [0, 1] |
| 11 | `packet_loss_path_b` | Drop count / total packets on S4 port 3 | [0, 1] |
| 12 | `jitter_path_a` | Std-dev of last 10 util_s3_s5 samples × 50 | [0, 1] |
| 13 | `jitter_path_b` | Std-dev of last 10 util_s4_s5 samples × 50 | [0, 1] |
| 14 | `bytes_path_a` | Cumulative TX bytes on S3 port 3 | bytes / 1e7 |
| 15 | `bytes_path_b` | Cumulative TX bytes on S4 port 3 | bytes / 1e7 |
| 16 | `time_of_day` | System clock | seconds-since-midnight / 86400 |
| 17 | `util_trend` | (avg_util_now − avg_util_prev) × 5 | [-1, 1] |
| 18 | `priority_flag` | 1.0 if any active flow has DSCP ≥ 34 | binary |
| 19 | `congestion_flag` | 1.0 if any util > 0.8 | binary |

---

## Feature Details

### Link utilisation (features 0–6)

Computed from TX byte deltas between consecutive `ovs-ofctl dump-ports` calls:

```python
mbps = (tx_bytes_now - tx_bytes_prev) * 8 / (dt * 1e6)
util = clamp(mbps / link_capacity_mbps, 0.0, 1.0)
```

Feature 4 uses S3→S5 capacity (50 Mbps), feature 5 uses S4→S5 capacity (100 Mbps). The asymmetric capacities mean 0.5 on feature 4 represents a higher absolute load than 0.5 on feature 5.

### Active flow counts (features 7–9)

From `ovs-ofctl dump-flows`:
- Path A: flows on S3 whose output port = 3 (→S5)
- Path B: flows on S4 whose output port = 3 (→S5)
- Path C: flows on S3 whose output port = 4 (→S4 cross-link)

The Ryu controller overwrites these three features every stats cycle with its own `path_counts` dictionary (more accurate than OvS flow parsing since the controller has full knowledge).

### Packet loss (features 10–11)

```python
loss = (rx_drop + tx_drop) / max(rx_pkts + tx_pkts, 1)
```

Values are naturally very low (typically 0.0) unless a link is congested.

### Jitter (features 12–13)

Rolling std-dev of the last 10 utilisation samples for each path, converted to a nominal "ms equivalent" (std-dev × 50 / 50 — keeps it in [0,1]):

```python
jitter = clamp(stdev(last_10_util_values) * 50.0 / 50.0)
```

Higher jitter means the path is fluctuating — a signal the agent should prefer the stable path.

### Cumulative bytes (features 14–15)

Absolute TX byte counters from OvS (not deltas). Reset when OvS restarts. Normalised by 10 million bytes (≈ 10 MB).

### Time of day (feature 16)

Encodes when the measurement was taken. Enables learning time-based patterns (e.g., busy-hour traffic). No special meaning in the current scenario.

### Utilisation trend (feature 17)

```python
trend = clamp((avg_util_now - avg_util_prev) * 5.0, lo=-1.0, hi=1.0)
```

Positive = network getting busier, negative = recovering. Helps the agent anticipate congestion before it happens.

### Priority flag (feature 18)

Set to `1.0` if any flow currently seen by OvS (on S3 or S4) has DSCP ≥ 34. Signals that a high-priority device (sensor, emergency, actuator) is active. The controller also sets this directly from its `flow_table`.

### Congestion flag (feature 19)

Set to `1.0` if any of the 7 link utilisation values exceeds 0.8 (80% of capacity). Acts as a binary "the network is stressed" signal.

---

## How the State is Built

1. `StatsCollector.get_state()` computes features 0–6, 10–16, 17–19 from OvS counters
2. `StatsCollector.get_state()` also computes features 7–9 from flow dump parsing
3. `IoTController._stats_loop` calls `get_state()` then overwrites features 7–9 with values from its own `path_counts` dict (authoritative source)
4. Feature 18 is overwritten with `1.0 if any flow in flow_table is_priority else 0.0`

---

## The LSTM Sequence

The DQN does not observe a single state snapshot — it observes a **sequence of 10 consecutive snapshots**:

```
state_buffer = deque(maxlen=10)
state_buffer.append(new_state)   # every 2 seconds

# Each action decision uses the full sequence:
state_seq = list(state_buffer)   # shape: (10, 20)
agent.select_action(state_seq)
```

This gives the LSTM 20 seconds of network history per decision. The LSTM's hidden state captures temporal patterns — e.g., "utilisation has been rising for the last 5 steps" — that a single snapshot would miss.

---

## Reward Function

```python
def compute_reward(state, action, next_state) -> float:
```

`state` is the state when the action was taken (or the last stats snapshot). `next_state` is the current state (2s later). The reward measures whether the chosen action led to good network conditions in `next_state`.

---

## Reward Components

### Latency reward

Measures how uncongested the chosen path's server-side link is (low utilisation = low queuing delay):

| Action | Formula |
|--------|---------|
| Path A | `1.0 - util_s3_s5` (feature 4) |
| Path B | `1.0 - util_s4_s5` (feature 5) |
| Path C | `0.5*(1-util_s3_s5) + 0.5*(1-util_s4_s5) - 0.1` |

Path C gets a -0.1 penalty because it uses two links (higher cumulative latency).

### Reliability reward

Measures packet delivery success on the chosen path:

| Action | Formula |
|--------|---------|
| Path A | `1.0 - loss_path_a` (feature 10) |
| Path B | `1.0 - loss_path_b` (feature 11) |
| Path C | `0.5*(1-loss_a) + 0.5*(1-loss_b)` |

### Throughput reward

Normalised cumulative bytes transferred on the chosen path:

| Action | Formula |
|--------|---------|
| Path A | `bytes_path_a` (feature 14, already in [0,1]) |
| Path B | `bytes_path_b` (feature 15) |
| Path C | `0.5*(bytes_path_a + bytes_path_b)` |

### Fairness reward

Encourages balanced load across both paths:

```python
fairness_r = 1.0 - abs(util_s3_s5 - util_s4_s5)
```

Applied regardless of which path was chosen. Maximum when both paths are equally loaded.

### Combined reward

```python
r = (R_LATENCY    * latency_r     # weight 0.4
   + R_RELIABILITY * reliability_r # weight 0.3
   + R_THROUGHPUT  * throughput_r  # weight 0.2
   + R_FAIRNESS    * fairness_r)   # weight 0.1
```

Maximum possible reward (all components = 1.0): `0.4 + 0.3 + 0.2 + 0.1 = 1.0`. In practice `0.5–0.8` is typical.

---

## Priority Multiplier

If `priority_flag` (feature 18) is 1 at the time of reward computation:

```python
if priority_flag:
    r *= R_PRIORITY_MUL   # = 5.0
```

This amplifies the reward signal 5× when high-priority traffic (emergency alerts, actuator commands) is active. It teaches the agent that routing decisions during priority events matter much more — wrong path choice during an emergency should be heavily penalised, correct choice strongly rewarded.

---

## Drop Action Reward

The drop action is handled separately:

```python
else:  # ACTION_DROP
    if congestion_flag:
        return 0.1   # small positive: sensible under full congestion
    return -1.0      # heavy penalty for dropping without good reason
```

The agent learns that dropping is acceptable only when the network is genuinely congested (all links > 80%). Random or unnecessary drops receive a -1.0 penalty, which propagates backward through the LSTM to discourage premature drops.

---

## Reward Clipping

Final clip:

```python
return float(np.clip(r, -1.0, 5.0))
```

The -1.0 floor covers drop-without-congestion. The 5.0 ceiling covers priority-multiplied rewards (max non-priority = 1.0, × 5 = 5.0).

---

## Example Reward Calculations

### Normal sensor flow on Path A — low load

```
util_s3_s5   = 0.1   loss_path_a = 0.0   bytes_path_a = 0.2
util_s4_s5   = 0.1   priority_flag = 0   congestion_flag = 0

latency_r    = 1.0 - 0.1 = 0.9
reliability_r = 1.0 - 0.0 = 1.0
throughput_r  = 0.2
fairness_r    = 1.0 - |0.1 - 0.1| = 1.0

r = 0.4*0.9 + 0.3*1.0 + 0.2*0.2 + 0.1*1.0
  = 0.36 + 0.30 + 0.04 + 0.10
  = 0.80
```

### Emergency flow on Path A — path congested

```
util_s3_s5   = 0.9   loss_path_a = 0.05  bytes_path_a = 0.7
util_s4_s5   = 0.2   priority_flag = 1   congestion_flag = 1

latency_r    = 1.0 - 0.9 = 0.1
reliability_r = 1.0 - 0.05 = 0.95
throughput_r  = 0.7
fairness_r    = 1.0 - |0.9 - 0.2| = 0.3

r = 0.4*0.1 + 0.3*0.95 + 0.2*0.7 + 0.1*0.3
  = 0.04 + 0.285 + 0.14 + 0.03
  = 0.495

r *= 5.0   # priority_flag active
  = 2.475
```

The agent learns to route emergency traffic to Path B instead (util = 0.2) — that would yield a much higher reward after the priority multiplier.

See also: [[Training_And_Persistence]] · [[Modules_Reference]] · [[Architecture]]
