# The Complex DQN Model — A Complete Conceptual Guide
### Upgraded AI Routing for the SDN IoT Network

---

## Table of Contents

1. [Why We Upgraded — The Limits of the Basic Model](#1-why-we-upgraded--the-limits-of-the-basic-model)
2. [The Five Upgrade Axes — An Overview](#2-the-five-upgrade-axes--an-overview)
3. [Axis 1 — Richer State Inputs (20 Features)](#3-axis-1--richer-state-inputs-20-features)
4. [Axis 2 — Deeper Network Architecture](#4-axis-2--deeper-network-architecture)
5. [Axis 3 — Dueling DQN Architecture](#5-axis-3--dueling-dqn-architecture)
6. [Axis 4 — LSTM Temporal Memory](#6-axis-4--lstm-temporal-memory)
7. [Axis 5 — Multi-Objective Reward Shaping](#7-axis-5--multi-objective-reward-shaping)
8. [How All Five Axes Work Together](#8-how-all-five-axes-work-together)
9. [The Full Data Flow — One Packet, Complete Journey](#9-the-full-data-flow--one-packet-complete-journey)
10. [Training the Complex Model](#10-training-the-complex-model)
11. [What the Model Now Knows That It Didn't Before](#11-what-the-model-now-knows-that-it-didnt-before)
12. [Tradeoffs and Honest Limitations](#12-tradeoffs-and-honest-limitations)
13. [Code Structure Summary](#13-code-structure-summary)

---

## 1. Why We Upgraded — The Limits of the Basic Model

The basic DQN model was a solid starting point. It took 8 numbers from the network, passed them through two hidden layers of 64 neurons each, and output 3 Q-values — one per path. It worked. But it had four specific blindspots that limited how intelligent it could really be.

### Blindspot 1 — It Only Saw the Present Moment

The basic model looked at a single snapshot of the network right now. It had no memory of what happened one second ago, or five seconds ago. This meant it could not detect trends.

Imagine link utilization readings over the last 10 seconds: `0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8`. The basic model sees `0.8` and thinks "this link is fairly busy." It routes to Path B.

But what it missed is the trend — the link is rising fast and will be completely saturated in 2 seconds. A smarter model would have moved the flow to Path B 4 seconds earlier, before congestion even started building.

### Blindspot 2 — It Didn't Know How Many Flows Were Already Routed

The basic model knew how busy each link was, but it didn't know *why*. If it routed everything to Path B, the next time it looked, Path B would show high utilization and it would route to Path A — which had just been emptied. This oscillation is a known failure mode called routing instability.

What was missing: knowing how many active flows are currently on each path. If Path B already has 40 flows and Path A has 2, the right choice is obvious — but the basic model couldn't see this.

### Blindspot 3 — The Reward Was Oversimplified

The basic model's reward was `1 / flow_completion_time`. That's it. The only thing it learned to optimise was speed. It had no concept of packet loss, no concept of fairness between flows, no concept that dropping an emergency alert is catastrophically worse than slightly delaying a firmware update.

This meant the model could learn a policy that was technically fast but practically unacceptable — sacrificing reliability for throughput.

### Blindspot 4 — The Value Estimation Problem

When most paths are equally fine (which is true most of the time in a lightly loaded network), the basic DQN struggles to learn meaningful differences between actions. All three Q-values end up similar, and the model can't reliably distinguish between "all paths are good" and "I don't know which path is good." These are very different situations that demand different behaviour.

---

## 2. The Five Upgrade Axes — An Overview

Each upgrade axis is independent. You can apply them in any order or combination. Together, they address all four blindspots identified above.

| Axis | What It Changes | Addresses Blindspot | Effort |
|------|----------------|---------------------|--------|
| 1 — Richer Inputs | State vector: 8 → 20 features | 2, partial 3 | Low |
| 2 — Deeper Network | More layers, BatchNorm, Dropout | None directly | Low |
| 3 — Dueling DQN | Split Value and Advantage heads | 4 | Medium |
| 4 — LSTM Memory | See last 10 states as a sequence | 1 | High |
| 5 — Reward Shaping | Multi-objective weighted reward | 3 | Medium |

The recommended order of implementation is: Axis 1 → Axis 5 → Axis 3 → Axis 4. Axis 2 is optional and only useful once the other axes are in place.

---

## 3. Axis 1 — Richer State Inputs (20 Features)

### The Conceptual Problem

The basic 8-feature state told the model about link utilization, queue lengths, average delay, and flow type. That's a partial picture. You're asking someone to navigate a city while only telling them the speed of traffic on two roads — without telling them how many cars are already on each road, whether there's an accident ahead, or what time of day it is.

### The New 20 Features

The expanded state has three categories of features: what the links look like right now, what the flows look like, and contextual information about time and urgency.

**Category A — Link Health (6 features, unchanged)**

These are the same as before: `link1_util`, `link2_util`, `link3_util` give instantaneous bandwidth consumption as a fraction from 0 to 1. `link1_queue`, `link2_queue`, `link3_queue` give packet buffer depth, which is the early warning signal that congestion is building before it shows up in utilization.

**Category B — Flow Population (4 new features)**

`active_flows_pathA` and `active_flows_pathB` tell the model how many independent flows are currently using each path. This is critical. Two paths can both show 50% utilization, but if Path A has that 50% coming from one elephant flow that is about to finish, while Path B has its 50% from 30 sensor flows that will keep running for hours, these are completely different situations.

`packet_loss_pathA` and `packet_loss_pathB` tell the model what percentage of packets sent down each path are being dropped. A path with 70% utilization and 0% packet loss is very different from one with 70% utilization and 2% loss. Loss means the switch buffer is overflowing — congestion has already crossed into damage.

**Category C — Flow-Level Context (4 new features)**

`jitter_pathA` and `jitter_pathB` measure variation in packet delay. A path where packets consistently take 10ms is good. A path where they sometimes take 5ms and sometimes take 50ms — same average, but terrible for video or sensor data — is jitter. Video streams are destroyed by jitter even when average delay looks acceptable.

`flow_bytes_so_far` tells the model how large the current flow has grown. A flow that has already transferred 400MB is almost certainly an elephant flow still running. A flow that has only sent 500 bytes is probably a sensor. This is a dynamic version of the static `flow_type` feature — it gives the model a running picture of what the flow actually is, not just what port it came in on.

**Category D — Temporal and Priority Context (4 new features)**

`time_of_day` is normalized from 0.0 to 1.0 representing midnight to midnight. This matters because IoT networks have patterns — cameras might stream more during business hours, firmware updates often run at night. The model can learn these patterns and pre-emptively prefer less loaded paths before congestion begins.

`link1_util_trend` is the derivative: the change in link utilization over the last 5 seconds. A positive value means congestion is growing. A negative value means it is shrinking. A value near zero means the link is stable. This is the feature that directly addresses Blindspot 1 — it gives the model a primitive version of temporal awareness even without LSTM.

`priority_flag` is binary: 0 or 1. It is set to 1 when Ryu classifies the flow as an emergency alert (based on a special port or DSCP marking). This allows the reward function to treat this flow differently and ensures the model learns that emergency flows must get the fastest path regardless of other considerations.

`avg_jitter_global` captures the overall network jitter across all recent flows. This provides a wider health signal beyond any individual path.

### Why Normalization Still Matters

All 20 features are normalized to the range 0.0 to 1.0 before entering the network. This is not optional — it is mandatory. Neural networks learn by adjusting weights based on the magnitude of numbers flowing through them. If `flow_bytes_so_far` is 450,000,000 (450MB in bytes) and `link1_util` is 0.85, the raw difference in scale would cause the network to pay almost exclusive attention to the byte count and largely ignore the utilization — not because it is more important, but simply because it is numerically larger.

Normalization removes scale from the equation entirely. Every feature is equally "loud" at the input. The network then learns which ones actually matter for routing quality.

---

## 4. Axis 2 — Deeper Network Architecture

### What Changes and Why

The basic model had this structure: Input (8) → Hidden (64) → Hidden (64) → Output (3).

The upgraded architecture looks like: Input (20) → Linear(256) → BatchNorm → ReLU → Dropout(0.2) → Linear(128) → BatchNorm → ReLU → Dropout(0.2) → Linear(64) → ReLU.

Three things were added: more neurons, BatchNorm, and Dropout.

### More Neurons

Going from 64 to 256 neurons in the first layer gives the network more "room to think." With 20 input features and complex interactions between them (the relationship between jitter and queue depth and flow type is not a simple formula), the network needs enough capacity to represent these interactions. 64 neurons for 20 inputs is like trying to solve a complex equation with too few variables — it will find an approximation but miss nuances.

### Batch Normalization

BatchNorm is a layer that sits between the linear transformation and the activation function. What it does, conceptually, is ensure that the numbers flowing through the network stay in a sensible range throughout training.

During training, the weights of early layers update constantly. This means the distribution of values flowing into later layers shifts constantly too — a problem called internal covariate shift. Later layers have to keep readapting to the changing distribution, which slows learning dramatically.

BatchNorm normalizes the output of each layer to have approximately zero mean and unit variance. This keeps the signal stable throughout the network, allowing learning to happen in all layers simultaneously rather than in sequence. The result is significantly faster convergence and more stable training.

### Dropout

Dropout randomly sets 20% of neuron outputs to zero during each training step. This sounds counterproductive — why deliberately damage the network while training?

The reason is overfitting. Without Dropout, the network can learn to rely on very specific combinations of neurons to memorize training patterns. When it encounters a new network state it hasn't seen before, it fails because those specific memorized patterns don't apply.

Dropout forces the network to develop redundant, distributed representations. Every neuron must learn to be useful even when 20% of its neighbours are absent. This produces a model that generalizes much better to new situations — which in a live network means better routing decisions for traffic patterns that didn't exist during training.

### Honest Assessment

Axis 2 alone produces limited improvement. A deeper network with the same 8 basic inputs just has more capacity to overfit those 8 features. The real value of the deeper architecture emerges when combined with Axis 1 (more inputs to process) and Axis 4 (sequence inputs that need more representational power). Think of Axis 2 as infrastructure — it doesn't help on its own, but it enables the other axes to reach their full potential.

---

## 5. Axis 3 — Dueling DQN Architecture

### The Conceptual Problem with Plain DQN

In a plain DQN, the network outputs three Q-values: Q(s, Path A), Q(s, Path B), Q(s, Path C). Each value estimates "how good is my total future reward if I choose this action in this state."

The problem is that in many states, the action doesn't matter much. When the network is nearly empty and all paths are healthy, all three Q-values should be approximately equal and high. The model needs to learn "this is a good state" and "actions are roughly equivalent here" simultaneously. But in a plain DQN, these two pieces of information are entangled in the same three numbers. The network has to represent both the goodness of the state and the relative advantage of each action in a single output.

This entanglement slows learning. When the network tries to update Q(s, Path A) based on experience, it inadvertently distorts the representation of how good the state is overall — which then contaminates the estimates for Path B and Path C.

### The Dueling Solution

The Dueling DQN splits the network's final section into two separate streams before combining them for the output.

The first stream is the Value stream. It takes the shared representation and outputs a single number: V(s). This is the model's estimate of "how good is this state, regardless of which action I take?" If all links are congested, V(s) is low. If all links are free, V(s) is high.

The second stream is the Advantage stream. It takes the same shared representation and outputs three numbers: A(s, Path A), A(s, Path B), A(s, Path C). Each Advantage value answers: "relative to the average, how much better or worse is this specific action in this state?"

The final Q-value for each action is computed as:

```
Q(s, a) = V(s) + A(s, a) - mean(A(s, all actions))
```

The subtraction of the mean is crucial. Without it, V(s) and A(s, a) are not uniquely determined — you could add any constant to V and subtract it from all A values and get the same Q. Subtracting the mean forces the A values to sum to zero, which makes V(s) unambiguously represent the state value.

### Why This Is More Powerful

Consider a specific scenario: all three paths are heavily congested. In this state, the action doesn't matter much — all choices lead to poor performance.

In a plain DQN, the network must update Q(Path A), Q(Path B), and Q(Path C) separately every time it experiences this state. Each update is noisy. The three values slowly converge on being roughly equal, but it takes many experiences because the entanglement means updating one disrupts the others.

In a Dueling DQN, the network quickly learns V(s) is low — because every action in this state leads to poor outcomes. The Advantage stream simultaneously learns that A(Path A) ≈ A(Path B) ≈ A(Path C) ≈ 0 — no action is significantly better than average. These two learning tasks reinforce each other rather than interfering.

Then in a different state where Path A is free and Path B is congested, the Advantage stream rapidly learns A(Path A) is high and A(Path B) is low. The Value stream simultaneously updates to reflect whether this is a generally good or bad state. The two pieces of information are learned in clean parallel rather than getting tangled.

### Where the Split Happens in the Architecture

The shared layers (LSTM output → Linear(256) → Linear(128) → Linear(64)) produce a 64-dimensional representation vector. This is the shared understanding of the current situation.

From here, the Value stream is: Linear(64 → 32) → ReLU → Linear(32 → 1). Just one output neuron for the state value.

The Advantage stream is: Linear(64 → 32) → ReLU → Linear(32 → 3). Three output neurons, one per action.

These are then combined with the formula above to produce the final Q-values.

---

## 6. Axis 4 — LSTM Temporal Memory

This is the most architecturally significant upgrade. It fundamentally changes what information the model reasons about — from a single snapshot to a sequence of events.

### The Conceptual Problem

Every routing decision in the basic model was made by looking at the network at a single instant. The model had no concept of whether the current state was temporary or persistent, getting better or getting worse, the result of a burst or a steady state.

This matters enormously in practice. Consider two situations that produce identical instantaneous state vectors:

Situation A: The network has been heavily congested for the last 30 seconds. Link 1 is at 85% utilization. There are dozens of flows established on Path A. Congestion is stable.

Situation B: Congestion just appeared 2 seconds ago. Link 1 shot from 20% to 85% in a single burst. This is probably one elephant flow that just started. It will end soon.

In Situation A, the right action is to aggressively reroute all new flows to Path B — congestion is persistent and Path A will stay saturated.

In Situation B, the right action might be to wait a few seconds before rerouting — the burst may clear on its own, and rerouting everything now will only cause unnecessary disruption.

The basic model cannot distinguish between these two situations. They look identical to it. The LSTM can.

### What LSTM Means — Long Short-Term Memory

LSTM is a type of recurrent neural network layer designed specifically to learn patterns in sequences. Instead of processing one input independently, it processes a sequence of inputs and maintains a hidden state that carries information forward from earlier in the sequence.

The LSTM has two pieces of internal memory: the hidden state and the cell state. At each time step, it reads the current input and its previous hidden state, and decides three things:

What to forget from the cell state — information from the past that is no longer relevant. If link utilization has been dropping consistently, the memory of the earlier high values should fade.

What to add to the cell state — new information from the current input that is important to remember. If utilization just spiked sharply, this should be written into memory.

What to output as the new hidden state — a filtered view of the cell state that is relevant for the current decision.

These decisions are made by three separate gating mechanisms (Forget Gate, Input Gate, Output Gate), each of which is a small neural network that learns its own logic during training. The LSTM does not need to be told explicitly what to remember — it learns from the data which patterns in the sequence are predictive of good routing outcomes.

### The Sequence Window

The model maintains a rolling window of the last 10 state snapshots. Each snapshot is a 20-feature vector collected every 2 seconds. So the LSTM sees 20 seconds of network history at each decision point.

The input tensor shape is: `(batch_size, 10, 20)` — batch of sequences, each sequence is 10 timesteps, each timestep is 20 features.

The LSTM processes this sequence step by step, from the oldest state to the most recent. At the end of the sequence (the current moment), the LSTM's hidden state is a 128-dimensional vector that encodes a compressed summary of the last 20 seconds of network behaviour. This summary is then passed into the Dueling DQN layers for the routing decision.

### What the LSTM Actually Learns to Detect

During training, the LSTM learns to encode specific temporal patterns that are predictive of routing quality. These patterns are not programmed in — they emerge from the training data. But based on how IoT networks behave, we expect the LSTM to learn to recognise the following:

Rising congestion: when `link_util` has been increasing for several consecutive timesteps, the hidden state should encode "congestion is building on this path — avoid it for new flows."

Burst detection: when utilization jumped suddenly from low to high in a single timestep, the hidden state should encode "this is a burst — it may be temporary — don't overreact by rerouting everything."

Periodic patterns: when the same pattern of congestion occurs at the same time each day (morning camera traffic, midday firmware updates), the LSTM can encode "this is a recurring pattern — pre-emptively route away from Path A in the mornings."

Flow lifecycle: when `flow_bytes_so_far` has been growing steadily for 10 timesteps, the LSTM learns "this is a long-running elephant flow that will continue — route around it, not through it."

None of these pattern recognitions are explicitly programmed. They are relationships that the LSTM discovers by repeatedly experiencing the consequences of routing decisions made in these contexts.

### Why the Hidden State Is Maintained Between Decisions

A subtle but important point: the LSTM's hidden state is not reset between every routing decision. It persists across decisions for the same switch, accumulating a running representation of network history. This means the model's "memory" is genuinely continuous — if a flow starts at time T and the network is checked again at T+2s, T+4s, T+6s, the LSTM's understanding of that flow's trajectory evolves continuously rather than starting fresh each time.

---

## 7. Axis 5 — Multi-Objective Reward Shaping

### Why the Original Reward Was Inadequate

The original reward `1 / flow_completion_time` taught the model one thing: get flows to finish faster. That's a reasonable proxy for network performance in simple scenarios, but it creates several problems in a real IoT network:

It treats all flows as equivalent. A 10ms delay reduction on a bulk firmware download gets the same reward signal as a 10ms delay reduction on an emergency cardiac monitor reading. These are not equivalent.

It ignores reliability. A routing choice that completes a flow 5% faster but drops 3% of packets could receive a higher reward than one that is slightly slower but delivers every packet. In safety-critical IoT applications, this is backwards.

It ignores the effect on other flows. A greedy routing decision that speeds up one flow by monopolising a path might slow down 10 other flows. The original reward function is entirely flow-centric — it has no concept of network-wide fairness.

### The Multi-Objective Reward Formula

The upgraded reward combines four components with learned weights:

```
reward = w1 × latency_reward
       + w2 × reliability_reward
       + w3 × throughput_reward
       + w4 × fairness_reward
       × priority_multiplier
```

Each component captures a different aspect of routing quality.

### Component 1 — Latency Reward

```
latency_reward = 1 / (measured_delay_ms + epsilon)
```

This is the original reward, now as one component among several. It rewards routing decisions that result in low end-to-end delay. The `epsilon` prevents division by zero if delay is measured as zero.

For a sensor flow that completed with 5ms delay: `1 / 5 = 0.20`.
For a sensor flow that completed with 50ms delay: `1 / 50 = 0.02`.

Weight: `w1 = 0.4` — latency is the primary concern for most IoT traffic.

### Component 2 — Reliability Reward

```
reliability_reward = 1.0 - packet_loss_rate        if loss < 0.01
reliability_reward = -5.0 × packet_loss_rate        if loss >= 0.01
```

Below 1% packet loss, this component adds a positive bonus proportional to reliability — near-zero loss is rewarded as good. Above 1% loss, the penalty becomes steeply negative. This non-linearity is deliberate: the model should learn that small amounts of packet loss are acceptable, but moderate loss should be strongly avoided.

The steep penalty at higher loss rates reflects the reality of IoT communication — if a temperature sensor drops 5% of its readings, the data stream is no longer reliable enough for process control. The reward function encodes this sharp cliff in acceptability.

Weight: `w2 = 0.3` — reliability is the second priority.

### Component 3 — Throughput Reward

```
throughput_reward = bytes_delivered / (flow_duration × link_capacity)
```

This measures how efficiently the path's capacity was used. A flow that transferred 4MB in 2 seconds on a 5Mbps link has throughput efficiency of `4,000,000 / (2 × 625,000) = 3.2`. Normalized to a 0-1 range, this rewards using available bandwidth effectively.

This component matters specifically for video and elephant flows where the goal is sustained high throughput rather than minimum latency. The multi-objective reward lets the model optimise for latency on sensor flows and throughput on bulk flows — different objectives for different traffic types.

Weight: `w3 = 0.2` — throughput is third priority, important mainly for large flows.

### Component 4 — Fairness Reward

```
fairness_reward = jain_fairness_index(all_active_flows)
```

Jain's Fairness Index is a standard metric from network engineering. Given a set of flows with throughputs `x1, x2, ..., xn`, it is calculated as:

```
J = (sum of xi)^2 / (n × sum of xi^2)
```

The result is always between 0 and 1. A value of 1.0 means all flows are getting exactly equal throughput — perfect fairness. A value near 0 means one flow is monopolising the network at the expense of others.

Including this in the reward teaches the model that routing decisions affecting other flows matter. Without this component, the model would learn to be entirely greedy — maximising performance for the current flow without considering the 40 other flows sharing the network.

Weight: `w4 = 0.1` — fairness is a soft constraint rather than a primary objective.

### The Priority Multiplier

```
if priority_flag == 1:
    total_reward = total_reward × 5.0
```

When a flow is marked as high-priority — an emergency alert, a medical device reading, a safety-critical sensor — the entire reward is multiplied by 5. This teaches the model that the consequences of routing decisions for these flows are five times more important than for normal flows.

The result is that after training, the model learns a strong bias: when a priority flow appears, it should receive the best available path even if this means slightly degrading throughput for other flows. This preference is learned, not hardcoded — the model discovers through training that high-priority flows deserve special treatment because the reward signal is so much stronger for those decisions.

### Tuning the Weights

The weights `w1, w2, w3, w4` are hyperparameters that you set based on your network's requirements. For a hospital IoT network where reliability is paramount, you might use `w2 = 0.5, w1 = 0.3, w3 = 0.1, w4 = 0.1`. For an industrial IoT network where throughput is the primary concern, `w3 = 0.4, w1 = 0.3, w2 = 0.2, w4 = 0.1` makes more sense.

The model does not know what the weights mean. It just sees that certain routing decisions consistently produce higher numbers than others, and it learns to make those decisions. The weights are the mechanism by which human knowledge about network requirements is injected into the learning process.

---

## 8. How All Five Axes Work Together

The five axes are not independent improvements that each help equally in isolation. They form a system where each axis unlocks or amplifies the others.

### The Dependency Chain

Axis 1 (richer inputs) is the foundation. Without more features, Axis 2 (deeper network) has nothing extra to process. Axis 4 (LSTM) can still work without extra features, but richer features give the LSTM richer patterns to learn over time. Axis 5 (reward shaping) is independent of the architecture — it can be applied regardless of what other axes are active.

Axis 3 (Dueling DQN) benefits most when the action space has states where all actions are approximately equal — which is much more common with a well-trained model that has good state representations from Axes 1 and 4. With only 8 basic features, many states are ambiguous and the Value/Advantage decomposition is harder to learn cleanly.

The full synergy is: LSTM (Axis 4) builds a rich temporal representation from the expanded features (Axis 1). This representation is large enough to benefit from the deeper layers (Axis 2). The Dueling architecture (Axis 3) cleanly separates state quality from action quality in this rich representation. And the multi-objective reward (Axis 5) provides training signal that reflects the actual complexity of routing goals.

### The Information Flow Through the Full Model

When a new flow arrives and a routing decision is needed:

The current network state is measured: 20 features from OvS statistics, packet headers, and system clock. This snapshot is added to the rolling buffer of the last 10 states.

The buffer, shape (1, 10, 20), is passed into the LSTM. The LSTM processes all 10 timesteps sequentially, building up its hidden state. At the end, the 128-dimensional hidden state encodes the network's recent history — not just what it looks like now, but how it has been behaving.

This 128-dimensional vector enters the shared fully-connected layers: Linear(128→256) → BatchNorm → ReLU → Dropout → Linear(256→128) → BatchNorm → ReLU → Dropout → Linear(128→64) → ReLU. These layers transform the temporal representation into a form useful for routing decisions.

The 64-dimensional result enters the Dueling split. The Value stream outputs V(s): a single number representing how good the overall network state is. The Advantage stream outputs A(s, a) for each of the 3 paths: how much better or worse is each specific action relative to average.

These combine: Q(s, a) = V(s) + A(s, a) - mean(A). Three final Q-values, one per path.

The action with the highest Q-value is selected. This maps to a physical port number on the switch. Ryu sends a FlowMod. The packet exits the switch on that port.

---

## 9. The Full Data Flow — One Packet, Complete Journey

To make everything concrete, here is a complete trace of a single video flow arriving at the network after the complex model is deployed.

A camera (10.0.0.3) starts sending a video stream to the server (10.0.0.10) on UDP port 5006. The first packet arrives at OvS Switch S1 on port 1.

OvS checks its flow table. No matching rule exists. Table-miss: the packet is sent to the Ryu controller as a PacketIn event.

Ryu's `packet_in_handler` receives the event. It parses the packet: UDP, dst_port=5006. Classification: `flow_type = 0.33` (video). `priority_flag = 0` (not emergency). `flow_bytes_so_far = 0.0` (just started).

Ryu queries OvS for current statistics: `ovs-ofctl dump-ports sdn-br`. It retrieves bytes/sec per port, queue depths, and timestamps to compute delay. It calculates all 20 state features and normalizes them.

It also queries the flow count per path from its internal flow table tracker: `active_flows_pathA = 12`, `active_flows_pathB = 3`. Packet loss rates from recent flow records: `loss_pathA = 0.001`, `loss_pathB = 0.0`. Jitter from timestamp variance: `jitter_pathA = 0.12`, `jitter_pathB = 0.03`.

The current state vector (20 numbers, all normalized) is appended to the 10-step rolling buffer. The oldest state is dropped.

The buffer `(1, 10, 20)` is sent to the Flask REST API: `POST /api/routing`.

The Flask API passes the buffer to the DQN agent's `select_action` method. The buffer becomes a PyTorch tensor. It passes through the LSTM layer, which processes all 10 timesteps and produces a 128-dimensional hidden state. This hidden state encodes the last 20 seconds of network history — including the fact that Path A has been slowly filling up over the last few timesteps while Path B has been idle.

The hidden state passes through the shared FC layers with BatchNorm and Dropout applied. It enters the Dueling split.

Value stream: V(s) = 0.72. Network is reasonably healthy overall.
Advantage stream: A(Path A) = -0.31, A(Path B) = +0.44, A(Path C) = -0.13.

Q-values:
- Q(Path A) = 0.72 + (-0.31 - 0.00) = 0.41
- Q(Path B) = 0.72 + (0.44 - 0.00) = 1.16
- Q(Path C) = 0.72 + (-0.13 - 0.00) = 0.59

*(Note: the mean of A is approximately 0.00 in this example after centring)*

argmax = Path B. Action = 1. Port = 3.

Flask returns: `{"action": 1, "port": 3, "path": "S1 → S3 → Server2"}`.

Ryu builds a FlowMod: match `src=10.0.0.3, udp_dst=5006`, action `output port 3`, idle_timeout=30s, hard_timeout=120s. This is sent to OvS via OpenFlow TCP:6633.

OvS installs the rule in its flow table. The first packet is forwarded immediately via PacketOut. Every subsequent packet from this camera matching the rule is forwarded at hardware speed, directly by the switch, with no controller involvement.

The camera's video stream now flows through S3 to Server2, on Path B — the less congested path with lower jitter, better suited for a continuous video stream.

---

## 10. Training the Complex Model

### What Changes in Training

The training loop is conceptually the same as the basic model: observe state, pick action, receive reward, store experience, sample batch, train. But the details are more complex.

The replay buffer now stores sequences, not individual state vectors. Each experience tuple is: `(state_sequence, action, reward, next_state_sequence, done)` where each sequence is `(10, 20)`. The buffer capacity stays at 10,000 experiences, but each experience is now a 10-step window rather than a single snapshot.

Training a single batch now involves:

Sampling 64 sequence tuples from the buffer. Passing all 64 sequences through the LSTM in parallel — `(64, 10, 20)` input tensor → `(64, 128)` hidden state output. Passing through shared FC layers, then the Dueling split. Computing Q-values for current states. Computing target Q-values using the target network for next states. Computing the MSE loss between predicted and target Q-values. Backpropagating through the Dueling heads, through the FC layers, and through the LSTM — adjusting all weights.

### The Target Network

The target network — a frozen copy of the Q-network updated every 100 steps — is even more important in the complex model than in the basic one. The LSTM's temporal nature means that small changes in early-layer weights can cascade into large changes in the final Q-values. The target network provides a stable training signal that prevents the entire sequence processing from oscillating during learning.

### Prioritized Experience Replay

A further enhancement to training: instead of sampling the replay buffer uniformly at random, we sample with probability proportional to the magnitude of the TD error — the difference between the predicted Q-value and the target Q-value for each experience.

Experiences where the prediction was very wrong are sampled more often. This focuses training on the situations the model is currently most confused about. Experiences where the model already predicts correctly are sampled rarely — training on them adds little information.

This is called Prioritized Experience Replay (PER) and significantly speeds up convergence, especially for the LSTM model where learning temporal patterns in rare situations (like sudden congestion bursts) is critical but those situations appear infrequently in the buffer.

### Expected Training Duration

With all five axes combined, the model takes approximately 3,000 to 5,000 training episodes to converge. At 2 to 5 seconds per episode in a Mininet simulation, this is 2 to 7 hours of training. This is run offline — the model trains on simulated traffic, and the saved weights are loaded for the live demo.

The model starts entirely random (epsilon = 1.0) and the LSTM's hidden state initializes to zeros. Early episodes produce terrible routing — the model explores randomly and the LSTM has nothing in its memory yet. By episode 500, the model shows measurable improvement over random. By episode 2000, it typically outperforms ECMP. By episode 4000, it reliably outperforms both baselines under adversarial traffic conditions.

---

## 11. What the Model Now Knows That It Didn't Before

After training, the upgraded model has internalized a set of routing intuitions that the basic model could never develop. These are not programmed rules — they are patterns discovered by the model through experience.

**Pattern 1 — Congestion Forecasting**
The LSTM learns that when `link_util` increases by more than 0.05 per timestep for three consecutive steps, the path will be saturated within 10 seconds. It learns to route new flows away from this path before the saturation is visible in the instantaneous state — a form of predictive routing.

**Pattern 2 — Burst vs Sustained Congestion**
When utilization jumps sharply in a single timestep (burst pattern in the LSTM's input), the model learns to be conservative about rerouting — the burst may clear. When utilization has been slowly rising for 8 of the last 10 timesteps, the model routes aggressively away, recognising sustained growth.

**Pattern 3 — Flow Type × Path State Matching**
The model learns that video flows (medium bandwidth, jitter-sensitive) should prefer paths with low `jitter` and moderate utilization rather than low utilization alone. Sensor flows should prefer paths with low queue depth since they need reliable low-latency delivery. Elephant flows should be directed to whichever path has the most spare capacity, regardless of jitter.

**Pattern 4 — Priority Preemption**
The model learns that when `priority_flag = 1`, it should route to the best available path regardless of what is currently using it — because the reward signal is 5x larger for those decisions, the model learns a strong unconditional preference for emergency flows.

**Pattern 5 — Path Rebalancing**
The model learns that when one path has significantly more active flows than another (from the `active_flows` features), routing new flows to the less populated path is almost always better — even if their instantaneous utilization metrics look similar — because the populated path is more likely to become congested as those flows progress.

---

## 12. Tradeoffs and Honest Limitations

No model is perfect. The upgraded model introduces genuine improvements but also genuine costs and limitations that must be understood.

### Increased Latency for the First Packet

The basic model's forward pass took approximately 1ms. The LSTM-based model takes approximately 5-8ms for the first packet of each flow, because the LSTM must process a 10-step sequence rather than a single vector.

In practice, the first-packet decision cost is acceptable because subsequent packets follow the installed flow rule at hardware speed. But in networks where even the first packet's latency is critical — such as networks carrying real-time control signals — this 5-8ms added latency may be unacceptable. For sensor data where packets arrive every 5 seconds, 8ms is completely invisible.

### Training Instability with LSTM

LSTM models are harder to train than plain feedforward networks. The hidden state can become saturated — stuck at extreme values — especially early in training when the model is exploring randomly. Gradient clipping (limiting the maximum gradient magnitude during backpropagation) is essential to prevent the training from diverging. This is a hyperparameter that requires tuning.

### The Window Size Assumption

The LSTM window of 10 timesteps at 2-second polling intervals gives 20 seconds of history. This is a design choice. If your network's congestion patterns operate on longer timescales — for example, a firmware update that runs for 10 minutes — 20 seconds of history may not be enough to distinguish it from a temporary burst. Increasing the window size to 30 or 50 timesteps increases the LSTM's memory but also increases computational cost and the number of training episodes needed to fill the buffer with meaningful sequences.

### The Reward Weights Are Assumptions

The weights `w1=0.4, w2=0.3, w3=0.2, w4=0.1` are not derived from data — they are engineering judgments about relative importance. Different operators with different network requirements would choose different weights. There is no objective way to determine the "correct" weights without a formal specification of what the network is optimising for. This is a feature, not a bug — it is the mechanism for encoding domain knowledge — but it means the model's behaviour depends on human judgment that must be validated.

### Generalisation Limits

The model is trained on Mininet simulations. Real IoT networks have behaviours that simulators do not perfectly capture: variable WiFi interference, device-level retransmission behaviour, routing protocol interactions, physical layer errors. The model may encounter real-world state patterns that are outside its training distribution and make poor decisions. Continued online learning — training on live traffic after initial deployment — helps close this gap but introduces the risk of the model drifting toward optimising the specific live environment rather than generalising.

---

## 13. Code Structure Summary

The upgraded model changes five files compared to the basic implementation.

`ai_agent/environment.py` grows from 8 features to 20 in `get_state()`. The reward function becomes the multi-objective formula with four components and the priority multiplier. The rolling state buffer is introduced here — each call to `get_state()` appends to a deque of length 10 and returns the full sequence.

`ai_agent/dqn_agent.py` is the largest change. The `QNetwork` class replaces the simple feedforward network with the LSTM layer followed by the shared FC layers with BatchNorm and Dropout, then the Dueling split into Value and Advantage heads. The `ReplayBuffer` now stores sequences rather than single state vectors. The training loop adds gradient clipping and optionally implements prioritized sampling.

`controller/sdn_controller.py` adds the 12 new feature calculations to the state-building logic: active flow counts per path (tracked in an internal dict), packet loss rates computed from consecutive FlowStats polls, jitter computed from timestamp variance in flow records, and the priority flag derived from DSCP or port-based classification.

`monitoring/stats_collector.py` adds per-path flow counting by tracking which port each installed flow is directed to, and adds jitter calculation alongside the existing utilization and queue depth metrics.

`api/rest_api.py` updates the input shape from a flat 8-vector to a 10×20 sequence tensor, and adds the `/api/feedback` endpoint to accept the multi-component reward breakdown for logging and debugging.

---

*Complex DQN Model Documentation v1.0*
*AI-Driven SDN IoT Routing System*
