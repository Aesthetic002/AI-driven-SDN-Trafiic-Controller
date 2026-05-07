# Feature Engineering
### From Raw Switch Statistics to Clean AI Inputs

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

Imagine you're a doctor who wants to assess a patient's cardiovascular health. The raw data you have is:
- 1,000 heartbeat timestamps captured by an EEG machine
- Raw blood oxygen saturation readings every 100ms
- Body temperature in Kelvin

To get useful information from this, you need to:
1. **Transform:** Convert Kelvin to Celsius. Convert heartbeat timestamps to "beats per minute."
2. **Compute derived features:** Calculate heart rate variability from the timestamps. Compute the trend (is heart rate rising over the last 5 minutes?).
3. **Normalize:** Put everything on a comparable scale so a doctor can look at all numbers at once.

**Feature engineering is the same process — applied to network data.**

The AI cannot directly use raw OvS port counters (`rx_bytes=147,382,291`). It needs clean, normalized features that capture the network's state in a form useful for decision-making (`link1_util=0.87, link1_util_trend=+0.04`).

---

## 2. Technical Explanation

### Data Sources

All features are derived from three sources:

| Source | Raw Data | Poll Method |
|---|---|---|
| **OvS port statistics** | rx_bytes, tx_bytes, packet counts per port per switch | `ovs-ofctl dump-ports` or StatsRequest OpenFlow message |
| **Ryu flow table tracker** | Active flows per path, per-flow byte counts | Ryu-internal dictionary tracking installed FlowMod rules |
| **System clock** | Current timestamp, time of day | Python `time.time()`, `datetime.now()` |

### The `get_state()` Pipeline

```python
def get_state(self, flow_info):
    """
    Collect all 20 features, normalize, append to rolling buffer.
    Returns: numpy array of shape (10, 20)
    """
    now = time.time()
    
    # ── Category A: Link Health ────────────────────────────────────────
    stats = self._query_ovs_stats()           # dict: port → (rx_bytes, tx_bytes, queue_depth)
    
    delta_time = now - self.last_poll_time
    
    link1_bytes = stats['port_2']['tx_bytes'] - self.prev_stats.get('port_2_tx', 0)
    link2_bytes = stats['port_3']['tx_bytes'] - self.prev_stats.get('port_3_tx', 0)
    link3_bytes = stats['port_1']['tx_bytes'] - self.prev_stats.get('port_1_tx', 0)
    
    link1_util = (link1_bytes / delta_time) / LINK_CAPACITY_BYTES_PER_SEC  # S1→S2
    link2_util = (link2_bytes / delta_time) / LINK_CAPACITY_BYTES_PER_SEC  # S1→S3
    link3_util = link1_util  # S1 aggregation port (sum of all IoT devices)
    
    link1_queue = stats['port_2']['queue_depth'] / MAX_QUEUE_SIZE
    link2_queue = stats['port_3']['queue_depth'] / MAX_QUEUE_SIZE
    link3_queue = stats['port_1']['queue_depth'] / MAX_QUEUE_SIZE
    
    # ── Category B: Flow Population ───────────────────────────────────
    active_flows_A = len(self.path_flows.get('A', []))
    active_flows_B = len(self.path_flows.get('B', []))
    
    loss_A = self._compute_packet_loss('A')   # dropped / sent
    loss_B = self._compute_packet_loss('B')
    
    active_flows_A_norm = min(active_flows_A / MAX_FLOWS_EXPECTED, 1.0)
    active_flows_B_norm = min(active_flows_B / MAX_FLOWS_EXPECTED, 1.0)
    
    # ── Category C: Flow Context ──────────────────────────────────────
    jitter_A = self._compute_jitter('A') / MAX_JITTER_MS
    jitter_B = self._compute_jitter('B') / MAX_JITTER_MS
    
    flow_bytes = min(flow_info.get('bytes_so_far', 0) / LARGE_FLOW_THRESHOLD, 1.0)
    flow_type  = FLOW_TYPE_MAP.get(flow_info.get('type', 'unknown'), 0.5)
    
    # ── Category D: Temporal Context ──────────────────────────────────
    time_of_day = datetime.now().hour / 24.0
    
    util_trend = (link1_util - self.prev_util) / MAX_TREND
    util_trend = np.clip(util_trend, -1.0, 1.0)
    
    priority_flag = 1.0 if flow_info.get('priority', False) else 0.0
    
    avg_jitter = (jitter_A + jitter_B) / 2.0
    avg_delay_A = self._compute_avg_delay('A') / MAX_DELAY_MS
    avg_delay_B = self._compute_avg_delay('B') / MAX_DELAY_MS
    
    # ── Assemble & Update Buffer ──────────────────────────────────────
    state = np.array([
        link1_util, link2_util, link3_util,
        link1_queue, link2_queue, link3_queue,
        active_flows_A_norm, active_flows_B_norm,
        loss_A, loss_B,
        jitter_A, jitter_B,
        flow_bytes, flow_type,
        time_of_day, util_trend, priority_flag,
        avg_jitter, avg_delay_A, avg_delay_B
    ], dtype=np.float32)
    
    self.state_buffer.append(state)         # deque(maxlen=10)
    self.prev_util = link1_util
    self.last_poll_time = now
    self.prev_stats = stats
    
    return np.array(self.state_buffer)      # shape (10, 20)
```

### Jitter Computation

Jitter (delay variation) is computed from per-packet timestamps stored in a recent flow record:

```python
def _compute_jitter(self, path):
    timestamps = self.recent_timestamps.get(path, [])
    if len(timestamps) < 2:
        return 0.0
    
    delays = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
    return np.std(delays) * 1000  # Convert to milliseconds
```

Higher standard deviation = more variable delay = higher jitter.

---

## 3. Mathematical / Algorithmic Details

### Normalization

All features are mapped to [0.0, 1.0]:

| Feature | Formula | Clipping |
|---|---|---|
| Link utilization | `bytes_per_sec / link_capacity_bytes_per_sec` | clip to [0,1] |
| Queue depth | `queue_packets / max_queue_size` | clip to [0,1] |
| Active flows | `num_flows / max_flows_expected` | clip to [0,1] |
| Packet loss | already a fraction (dropped/sent) | clip to [0,1] |
| Jitter | `std_delay_ms / max_jitter_ms` | clip to [0,1] |
| Flow bytes | `bytes_so_far / large_flow_threshold` | clip to [0,1] |
| Flow type | lookup table: sensor=0.0, video=0.33, elephant=1.0 | n/a |
| Time of day | `hour / 24.0` | already in [0,1] |
| Util trend | `(util_t - util_{t-1}) / max_trend` | clip to [-1,1] |
| Priority flag | `1.0 if priority else 0.0` | binary |
| Avg delay | `mean_delay_ms / max_delay_ms` | clip to [0,1] |

### Reference Constants

| Constant | Value | Rationale |
|---|---|---|
| `LINK_CAPACITY_BYTES_PER_SEC` | 625,000 (5 Mbps) | Backbone link capacity |
| `MAX_QUEUE_SIZE` | 1,000 packets | OvS default queue depth |
| `MAX_FLOWS_EXPECTED` | 100 | Reasonable upper bound for experiment |
| `LARGE_FLOW_THRESHOLD` | 100 MB | Flows above this are certainly "elephant" |
| `MAX_JITTER_MS` | 50 ms | Jitter above this is severe degradation |
| `MAX_DELAY_MS` | 200 ms | Delay above this is unacceptable for IoT |
| `MAX_TREND` | 0.2 per 2-second step | Maximum realistic rate of utilization change |

### Poll Interval and Timing

- **Poll every 2 seconds** → 10 snapshots = 20 seconds of history for LSTM
- **Flow completion reported immediately** → reward computed as soon as flow ends
- **StatsReply latency** → typically <5ms on local network; acceptable for 2-second polling

---

## 4. Role in Our Project

Feature engineering is the **bridge** between the physical network and the AI model. Without good features:

- The AI is blind to important signals (trend, jitter, flow count)
- The AI cannot learn good policies regardless of architecture
- Training converges slowly or to a suboptimal policy

**The impact of adding each category of features:**

| Feature Category | Without It | With It |
|---|---|---|
| Link utilization only | AI knows congestion exists | Basic routing improvement |
| + Queue depth | AI knows congestion is building before packets drop | Early warning → proactive rerouting |
| + Flow counts | AI knows why congestion exists | Better prediction of future load |
| + Jitter | AI optimizes for video quality, not just throughput | Better video routing decisions |
| + Trend | AI predicts congestion onset | Pre-emptive routing before congestion hits |
| + Priority flag | AI gives emergency flows special treatment | Safety-critical IoT requirements met |

The jump from 8 features (basic model) to 20 features (complex model) is the single most impactful improvement after the LSTM architecture.

---

## 5. Interconnections

- [[State_Space]] — the destination of feature engineering; defines the 20 features and their meaning
- [[SDN_Controller]] — Ryu provides the raw data (PacketIn, StatsReply, flow table state) that features are computed from
- [[OpenFlow_Protocol]] — StatsRequest/StatsReply is the specific OpenFlow mechanism used to extract per-port byte counts
- [[LSTM_Memory]] — receives the 10-step sequence built by appending each new state snapshot to the rolling buffer
- [[DQN_Model]] — features are the input layer of the neural network; their quality directly bounds model performance
- [[Training_Process]] — feature extraction runs during every training episode; quality of features affects training speed

---

## 6. Advanced Insights

### The Temporal Alignment Problem

Features from different sources have different update frequencies:
- OvS port stats: updated every 2 seconds (polled)
- Ryu flow table: updated instantly (event-driven, when FlowMod is installed/removed)
- System clock: continuous

When the `get_state()` function runs, it assembles a snapshot from potentially stale sources (port stats might be up to 2 seconds old) and fresh sources (flow counts are current). This temporal misalignment introduces noise into the state vector.

Mitigation: Use the same timestamp for all features, and note staleness explicitly if needed. In practice, 2-second staleness is acceptable for 2-second polling intervals.

### Feature Importance Analysis

Not all 20 features contribute equally. After training, we can analyze which features the model pays most attention to using:

- **Permutation importance:** Zero out one feature at a time; measure drop in performance
- **Gradient saliency:** Compute `dQ/d(feature)` to see which input dimensions have the largest effect on Q-values
- **Attention weights:** If using Transformer instead of LSTM, attention weights directly indicate feature importance

Typically, `link_util_trend`, `active_flows_pathA/B`, and `priority_flag` would rank highest in our system.

### Feature Drift

Network conditions change over time. If the DQN is deployed on a network where utilization regularly exceeds 1.0 (normalized) because the actual link is faster than assumed, the clipping `clip(x, 0, 1)` will mask the difference. Features should be periodically recalibrated with updated normalization constants.

---

## 7. References for Further Study

- **Feature engineering for time series** — box-Jenkins methodology, moving averages, ARIMA residuals
- **Neural network input normalization** — LeCun et al., "Efficient BackProp" (2012) — why preprocessing inputs dramatically improves training
- **Jitter in real-time communications** — RFC 3550 "RTP: A Transport Protocol for Real-Time Applications" — formal definition of inter-arrival jitter
- **OpenTelemetry** — modern observability framework for producing rich telemetry from distributed systems
- **Topics to explore:** Online feature normalization (updating min/max statistics in production), Feature drift detection, Exponential weighted moving average (EWMA) for smoothed trend features, Kalman filter for noise-robust state estimation
