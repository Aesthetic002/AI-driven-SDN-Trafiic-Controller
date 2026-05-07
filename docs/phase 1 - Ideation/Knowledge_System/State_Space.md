# State Space
### What the AI Sees — The 20 Network Features

---

## Table of Contents

- [[#1. Intuition|1. Intuition]]
- [[#2. Technical Explanation|2. Technical Explanation]]
- [[#3. Mathematical / Algorithmic Details|3. Mathematical / Algorithmic Details]]
- [[#4. Role in Our Project|4. Role in Our Project]]
- [[#5. Interconnections|5. Interconnections]]
- [[#6. Advanced Insights|6. Advanced Insights]]
- [[#7. References for Further Study|7. References for Further Study]]

---

## 1. Intuition

Think of the AI as a doctor making a diagnosis. A bad doctor only checks one thing — "Is the patient's temperature above 38°C?" A good doctor uses many signals: blood pressure, heart rate, respiratory rate, oxygen saturation, lab results, and the patient's history over the past few hours.

Our upgraded AI uses 20 signals (features) to understand the current state of the network — compared to the basic model's 8.

The **state** is a snapshot of "what is the network like right now (and over the last 20 seconds)?" It is the input to the AI. Everything the AI knows about the world is contained in this vector.

If the state is wrong, incomplete, or poorly normalized, the AI will make bad routing decisions — regardless of how sophisticated its architecture is. **Garbage in, garbage out.**

---

## 2. Technical Explanation

### The Formal Definition

The state at time `t` is a vector:

```
s_t = [link1_util, link2_util, link3_util,
       link1_queue, link2_queue, link3_queue,
       active_flows_pathA, active_flows_pathB,
       loss_pathA, loss_pathB,
       jitter_pathA, jitter_pathB,
       flow_bytes_so_far,
       time_of_day,
       link1_util_trend,
       priority_flag,
       avg_jitter_global,
       flow_type,
       avg_delay_pathA, avg_delay_pathB]
```

All values are **normalized to [0.0, 1.0]** before entering the network.

### The Four Feature Categories

#### Category A — Link Health (6 features)

| Feature | Raw Source | Normalization | What It Captures |
|---|---|---|---|
| `link1_util` | OvS bytes/sec per port | ÷ link capacity | Fraction of bandwidth consumed on link 1 |
| `link2_util` | OvS bytes/sec per port | ÷ link capacity | Fraction of bandwidth consumed on link 2 |
| `link3_util` | OvS bytes/sec per port | ÷ link capacity | Fraction of bandwidth consumed on link 3 |
| `link1_queue` | OvS queue depth | ÷ max queue size | Buffer fill level — early congestion warning |
| `link2_queue` | OvS queue depth | ÷ max queue size | Buffer fill level on link 2 |
| `link3_queue` | OvS queue depth | ÷ max queue size | Buffer fill level on link 3 |

**Why queue depth matters:** Link utilization is a lagging indicator. Queue depth is a leading indicator. A link at 60% utilization with a completely full queue is about to drop packets. A link at 85% utilization with an empty queue is handling load fine. The queue is the "pressure gauge."

#### Category B — Flow Population (4 features)

| Feature | Raw Source | Normalization | What It Captures |
|---|---|---|---|
| `active_flows_pathA` | Ryu internal flow table | ÷ max expected flows | How many independent flows are currently on Path A |
| `active_flows_pathB` | Ryu internal flow table | ÷ max expected flows | How many independent flows are currently on Path B |
| `loss_pathA` | Per-flow packet counters | Already fraction (0–1) | Fraction of packets being dropped on Path A |
| `loss_pathB` | Per-flow packet counters | Already fraction (0–1) | Fraction of packets being dropped on Path B |

**Why flow count matters:** Two paths can both show 60% utilization. But if Path A has 1 elephant flow (which will finish soon and drop utilization to 0%) while Path B has 30 sensor flows (which will continue indefinitely), they are completely different futures. The AI needs to see this distinction.

#### Category C — Flow-Level Context (4 features)

| Feature | Raw Source | Normalization | What It Captures |
|---|---|---|---|
| `jitter_pathA` | Variance of packet timestamps on Path A | ÷ max expected jitter | Delay variation — critical for video quality |
| `jitter_pathB` | Variance of packet timestamps on Path B | ÷ max expected jitter | Delay variation on Path B |
| `flow_bytes_so_far` | Running byte count for current flow | ÷ large flow threshold (e.g. 100MB) | Dynamic estimate of flow size (grows over time) |
| `flow_type` | Classified from port: sensor=0.0, video=0.33, elephant=1.0 | Pre-encoded | What kind of traffic is this flow? |

**Why jitter matters beyond latency:** A video stream that receives packets every 33ms like clockwork is perfect. A video stream that receives packets at 10ms, then 100ms, then 5ms has the same average delay but looks choppy or freezes — because the client's playback buffer overflows or underflows. The AI needs to know jitter specifically, not just average delay.

#### Category D — Temporal and Priority Context (6 features)

| Feature | Raw Source | Normalization | What It Captures |
|---|---|---|---|
| `time_of_day` | System clock | hour/24 | Time fraction (0=midnight, 0.5=noon) — for learning daily patterns |
| `link1_util_trend` | (util_t − util_{t-5}) / 5 | Clipped to [−1, 1] | Rate of change of congestion — positive = rising |
| `priority_flag` | DSCP marking or port-based classification | 0 or 1 | Is this an emergency/safety-critical flow? |
| `avg_jitter_global` | Mean jitter across all recent flows | ÷ max expected jitter | Overall network health signal |
| `avg_delay_pathA` | Mean end-to-end measured delay on Path A | ÷ max expected delay (e.g. 200ms) | Average latency experienced on this path |
| `avg_delay_pathB` | Mean end-to-end measured delay on Path B | ÷ max expected delay | Average latency experienced on Path B |

---

## 3. Mathematical / Algorithmic Details

### Normalization Formula

```
feature_normalized = (raw_value − min_expected) / (max_expected − min_expected)
feature_clipped = clip(feature_normalized, 0.0, 1.0)
```

Example: Link utilization in bytes/second on a 5 Mbps link:
```
link1_util = bytes_per_sec / (5 × 125,000)   # 5 Mbps = 625,000 bytes/sec
```

### Trend Calculation

The trend feature is the numerical derivative over the last 5 timesteps:

```
util_trend_t = (util_t − util_{t-5}) / 5
```

This is then normalized by dividing by the maximum rate of change (e.g., 0.2 per second for a 5 Mbps link going from 0 to 100% in 5 seconds) and clipped to [−1, 1]:

```
util_trend_normalized = clip(util_trend_t / max_rate, −1, 1)
```

### Flow Type Encoding

| Traffic Type | Port | Encoded Value |
|---|---|---|
| Sensor (ESP32, small, periodic) | UDP 5005 | 0.00 |
| Video (camera, continuous stream) | UDP 5006 | 0.33 |
| Elephant (bulk transfer, TCP) | TCP 5007 | 1.00 |
| Unknown | any | 0.50 |

### The State Sequence (for LSTM)

Rather than a single 20-vector, the [[LSTM_Memory|LSTM]] receives a **sequence** of 10 consecutive snapshots:

```
State sequence = [s_{t-9}, s_{t-8}, ..., s_{t-1}, s_t]
Shape: (10, 20)
```

Each snapshot is collected every 2 seconds. So the sequence spans 20 seconds of network history.

---

## 4. Role in Our Project

The state space is the **interface between the physical network and the AI brain**. Everything the AI can learn is limited to what the state captures. If a feature is missing, the AI is blind to it.

**Specific examples of what each category enables:**

- Without `link1_util_trend`: The AI cannot predict onset of congestion — it can only react after the fact.
- Without `active_flows_pathA/B`: The AI cannot distinguish a temporary elephant from many persistent sensors at the same utilization level.
- Without `jitter_pathA/B`: The AI thinks two paths with identical average latency are identical — but one may be destroying video quality.
- Without `priority_flag`: The AI cannot give special treatment to emergency IoT flows.
- Without `flow_bytes_so_far`: The AI cannot dynamically identify an elephant that declared itself as unknown.
- Without `time_of_day`: The AI cannot learn "avoid Path A on weekday mornings."

The jump from 8 to 20 features is the single most impactful upgrade after LSTM — it directly determines the quality ceiling of everything the model can learn.

---

## 5. Interconnections

- [[Feature_Engineering]] — how raw OvS and Ryu data is collected, cleaned, and turned into these 20 numbers
- [[LSTM_Memory]] — consumes the 10-step sequence of state vectors; the temporal dimension of the state
- [[DQN_Model]] — uses the state vector as input to compute Q-values
- [[Reward_Function]] — some state features (like `loss_pathA`, `jitter`) are also inputs to reward calculation
- [[SDN_Controller]] — collects raw packet and port statistics used to build the state
- [[IoT_Traffic_Types]] — the traffic classifications that determine `flow_type` and `priority_flag`

---

## 6. Advanced Insights

### The Markov Property and its Violation

Q-learning assumes the environment is a **Markov Decision Process** — the current state contains all information needed to make the optimal decision. In reality, a single 20-feature snapshot violates this: whether the current congestion is temporary or permanent requires knowing the history.

The [[LSTM_Memory|LSTM's 10-step window]] partially restores the Markov property by including recent history in the state representation. This is called **state augmentation** — instead of a non-Markov state `s_t`, we use the augmented state `[s_{t-9}, ..., s_t]` which is approximately Markov for the timescales relevant to routing.

### Feature Selection Tradeoffs

Adding more features always comes with costs:
- More features = larger input to LSTM = more parameters = slower training
- More features = more OvS polling = higher controller overhead
- More features = more chance of irrelevant correlations confusing the model

Each of the 20 features was chosen because it directly affects routing quality for IoT traffic. Adding `CPU temperature of the IoT device` would add noise, not signal.

### Correlation Between Features

Some features are correlated: `link_util` and `link_queue` both rise together as congestion builds. Correlated features don't hurt neural networks the way they hurt linear models, but they mean the model has redundant information — which is actually useful robustness. If OvS can't compute queue depth for some reason, utilization alone still gives the congestion signal.

---

## 7. References for Further Study

- **Feature engineering for RL** — why state representation determines the ceiling of what a model can learn
- **State augmentation** — converting non-Markov observations into approximately Markov states via history stacking
- **Temporal feature engineering** — trend features, rolling statistics, exponential smoothing
- **Jain's Fairness Index** — measuring equitable resource distribution in networks
- **Topics to explore:** POMDP (Partially Observable MDP) for incomplete state, Recurrent policies for non-Markov environments, Attention mechanisms for state feature importance
