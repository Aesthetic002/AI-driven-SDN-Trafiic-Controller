# Reward Function
### What "Good Routing" Means — The Multi-Objective Signal

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

Imagine you're training a dog. Every time it does something right, you give it a treat. The dog doesn't understand abstract concepts like "good behavior" — it only learns from the treat signal. If you reward it every time it sits still, it will learn to sit still. If you reward it every time it fetches the ball, it will learn to fetch.

**The reward function is that treat signal for our AI.** It's the only way the AI knows whether its routing decision was good or bad. The AI doesn't understand "latency" or "packet loss" as human concepts — it only knows that higher numbers (more reward) mean it's doing something right.

**The key insight:** What you reward is what you get. If the reward function is too simple, the AI will optimize for the wrong thing.

**Our basic reward (too simple):**
```
reward = 1 / flow_completion_time
```
This rewards speed only. The AI could learn to be fast by dropping packets (shorter flow → faster completion). Or it could learn to monopolize one path for one flow, speeding it up while destroying everyone else's performance.

**Our upgraded reward (multi-objective):**
```
reward = w1×latency + w2×reliability + w3×throughput + w4×fairness
         × priority_multiplier
```
This teaches the AI to balance four competing objectives simultaneously — just like a human network engineer would.

---

## 2. Technical Explanation

### The Four Components

#### Component 1 — Latency Reward (weight: 0.4)

```python
latency_reward = 1.0 / (measured_delay_ms + 1e-6)
```

Measures how quickly packets are getting through. The epsilon (`1e-6`) prevents division by zero. As delay increases from 5ms to 50ms to 500ms, the reward drops from 0.20 to 0.02 to 0.002 — a non-linear penalty that is steeper at low delays (1ms improvement from 5ms to 4ms is more valuable than from 50ms to 49ms).

**Weight = 0.4:** Latency is the primary concern. Most IoT devices (sensors, cameras) are sensitive to delay. This is the dominant optimization target.

#### Component 2 — Reliability Reward (weight: 0.3)

```python
if packet_loss_rate < 0.01:     # Less than 1% loss
    reliability_reward = 1.0 - packet_loss_rate        # Positive: near-zero loss rewarded
else:                            # 1% or more loss
    reliability_reward = -5.0 * packet_loss_rate       # Steep negative penalty
```

The **non-linearity** is intentional and critical. Below 1% loss, small amounts of loss are treated leniently — some packet loss is acceptable and even expected (UDP doesn't guarantee delivery). Above 1% loss, the penalty is steep. At 5% loss, `reliability_reward = -0.25`, which overrides the latency and throughput rewards — signaling that this path is actively harmful.

**Why this cliff?** In IoT safety applications, a cardiac monitor that drops 5% of readings cannot be trusted for clinical use. The reward function encodes this sharp threshold.

**Weight = 0.3:** Reliability is the second priority.

#### Component 3 — Throughput Reward (weight: 0.2)

```python
throughput_reward = bytes_delivered / (flow_duration × link_capacity_bytes_per_sec)
```

Measures how efficiently bandwidth is used. A flow that delivers 4 MB in 2 seconds over a 5 Mbps (625 KB/s) link has efficiency `4,000,000 / (2 × 625,000) = 3.2`, normalized to [0,1] = high efficiency.

**Why this matters:** For video and elephant flows, the goal is sustained throughput. A routing decision that gives a video stream 3 Mbps on a 5 Mbps link (60% efficiency) is better than one that gives 1 Mbps (20% efficiency) even if the latency is similar.

**Weight = 0.2:** Throughput is tertiary — it matters most for large flows, not sensor readings.

#### Component 4 — Fairness Reward (weight: 0.1)

```python
# Jain's Fairness Index
def jain_fairness(throughputs):
    n = len(throughputs)
    return (sum(throughputs)**2) / (n * sum(x**2 for x in throughputs))
```

Jain's Fairness Index returns 1.0 when all flows get equal throughput, and approaches 0.0 when one flow monopolizes all bandwidth.

**Why fairness matters:** Without this component, the AI might learn a greedy policy — sacrifice many small sensor flows to optimize one large video flow's performance, maximizing its own immediate reward. Fairness is a soft constraint that teaches the AI that **all flows matter.**

**Weight = 0.1:** Fairness is a soft constraint, not a hard requirement.

### The Priority Multiplier

```python
if priority_flag == 1:
    total_reward *= 5.0
```

When a flow is marked as high-priority (emergency medical device, factory safety sensor), the entire reward is multiplied by 5. This does not change the shape of the reward — it amplifies the **learning signal** for priority flows.

The AI discovers through training that the consequences of routing decisions for priority flows are 5× more important. It develops a strong internal bias: when `priority_flag = 1`, route to the absolutely best available path, even if it comes at some cost to other flows.

**This is the mechanism for encoding domain knowledge (priority matters) into learned behavior (AI treats priority flows differently).**

---

## 3. Mathematical / Algorithmic Details

### Full Reward Formula

```
reward = (w1 × latency_reward
        + w2 × reliability_reward
        + w3 × throughput_reward
        + w4 × fairness_reward)
       × priority_multiplier
```

Where:
- `w1 = 0.4, w2 = 0.3, w3 = 0.2, w4 = 0.1` (sum to 1.0)
- `priority_multiplier = 5.0 if priority_flag else 1.0`

### Reward Range Examples

| Scenario | Latency | Reliability | Throughput | Fairness | Reward |
|---|---|---|---|---|---|
| Perfect sensor routing | 1.0 (5ms) | 0.99 (1% loss) | 0.3 (sensor is tiny) | 0.9 | **0.86** |
| Path A congested, sensor forced there | 0.02 (50ms) | -0.10 (2% loss) | 0.1 | 0.7 | **-0.001** |
| Fast video stream, Path B | 0.05 (20ms) | 1.0 (0% loss) | 0.8 (3Mbps/5Mbps) | 0.85 | **0.55** |
| Emergency sensor, priority | 1.0 (3ms) | 1.0 (0% loss) | 0.1 | 0.9 | **0.93 × 5 = 4.65** |
| Elephant on congested path | 0.004 (250ms) | -0.35 (7% loss) | 0.4 | 0.3 | **-0.065** |

### Reward Timing

The reward is computed **at flow completion** (or at a 30-second timeout). This is **episodic** reward — the AI makes a routing decision now but receives feedback when the flow ends.

This creates a **temporal credit assignment problem**: the routing decision was made at time T, but the reward arrives at T+10s (or T+30s for elephant flows). The [[DQN_Model|Bellman equation]] handles this by using the discount factor γ to bridge the gap — future rewards are worth `γ^n` of their face value, where n is the number of steps until the reward arrives.

---

## 4. Role in Our Project

The reward function is the **objective function** — the mathematical definition of what the AI is trying to achieve. It is the most important design decision in the entire system. Every other component (architecture, training, state) exists to optimize this objective efficiently.

**In our project specifically:**

The multi-objective reward allows the AI to handle three very different traffic types appropriately without separate models for each:

- For **sensor flows** (small, frequent): High latency weight rewards fast delivery. High reliability weight prevents data loss.
- For **video flows** (medium, continuous): Jitter is captured in the state; throughput and reliability weights together optimize for smooth streaming.
- For **elephant flows** (bulk, one-time): Throughput weight rewards efficient bandwidth use. Low fairness weight penalizes monopolization.
- For **emergency flows** (any type): Priority multiplier overrides all other considerations with a 5× amplification.

---

## 5. Interconnections

- [[DQN_Model]] — the reward is the training signal that shapes Q-values through the Bellman equation
- [[State_Space]] — `loss_pathA`, `jitter_pathA`, `active_flows` from the state are also inputs to the reward calculation
- [[Training_Process]] — shows where and when rewards are computed and stored
- [[Replay_Buffer]] — each experience tuple contains the reward value `(s, a, r, s', done)`
- [[IoT_Traffic_Types]] — flow type classification determines which objective dominates in the reward
- [[Exploration_vs_Exploitation]] — early in training, random actions produce highly variable rewards that teach the AI the full consequences of each action

---

## 6. Advanced Insights

### Reward Shaping and Its Risks

**Reward shaping** means designing additional terms in the reward to guide learning. The multi-objective reward is a form of reward shaping. The risk is **reward hacking**: the AI finds unexpected ways to maximize the reward that don't correspond to the intended behavior.

Example: If the fairness reward is computed only on currently active flows, the AI might learn to route elephant flows to a separate server (creating a new "active flow" group) where they're compared to each other — giving high fairness while starving the main network.

Mitigation: Carefully define what "all active flows" means, and validate reward behavior against edge cases before training.

### Weight Sensitivity Analysis

The weights w1, w2, w3, w4 determine the AI's priorities. Their sum is 1.0, so they're a distribution over objectives. Consider how different deployments would tune them:

| Deployment | w1 (latency) | w2 (reliability) | w3 (throughput) | w4 (fairness) |
|---|---|---|---|---|
| Hospital IoT (safety-critical) | 0.3 | 0.5 | 0.1 | 0.1 |
| Smart factory (throughput-heavy) | 0.2 | 0.2 | 0.5 | 0.1 |
| Smart home (balanced) | 0.4 | 0.3 | 0.2 | 0.1 |
| Research network (fairness-focused) | 0.25 | 0.25 | 0.25 | 0.25 |

The same model architecture can serve different deployments by only changing the reward weights during training.

### The "Reward is not Truth" Principle

The reward function is a proxy for what you actually want (SLA compliance, network health, zero dropped alarms). It is never a perfect proxy. The AI will optimize the proxy perfectly — and that optimization may diverge from the original intent in ways that only appear in production.

Always validate that the AI's learned behavior (observable policy) aligns with the intended behavior (what the reward was supposed to capture) before deployment.

---

## 7. References for Further Study

- **Reward shaping** — Ng et al., "Policy Invariance Under Reward Transformations" (1999) — when reward shaping guarantees optimal policy preservation
- **Multi-objective RL** — Roijers et al., "A Survey of Multi-Objective Sequential Decision-Making" — formal treatment of competing objectives
- **Jain's Fairness Index** — Jain et al., "A Quantitative Measure of Fairness and Discrimination for Resource Allocation in Shared Computer Systems" (1984)
- **Reward hacking / specification gaming** — Krakovna et al., "Specification Gaming: the flip side of AI ingenuity"
- **Topics to explore:** Constrained MDP (hard constraints instead of soft reward terms), Pareto-optimal policies for multi-objective problems, Inverse Reinforcement Learning (learn reward from expert demonstrations)
