# DQN Model
### Deep Q-Network — The AI Brain of the SDN Controller

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

Imagine you are navigating a city you've never been to. You don't know the traffic patterns, which roads get jammed at which times, or which shortcuts actually save time. So you start exploring — you try different routes and note which ones got you there faster. Over time, you build intuition: "In the morning, the highway jams up — take the side road." You never need to relearn that from scratch; the experience is stored.

**DQN is exactly this process, applied to network routing.**

- The "city" is the IoT network with its switches and links.
- The "routes" are Path A (S1→S2) and Path B (S1→S3).
- The "experience" is: every time the AI picks a path, it observes how well the flow performed and updates its understanding of that choice.
- The "AI agent" uses a **neural network** (the "deep" part) to remember and generalize from thousands of experiences — much more efficiently than a lookup table.

The word "Q" stands for **Quality**. The AI learns a function Q(state, action) = "how good is it to take this action in this situation?"

---

## 2. Technical Explanation

### What is Q-Learning?

Q-Learning is a **model-free reinforcement learning** algorithm. "Model-free" means the agent does not need a mathematical model of the environment — it learns directly from interaction.

The agent maintains a **Q-function**: `Q(s, a)` which estimates the expected cumulative future reward if the agent takes action `a` in state `s` and then follows its optimal policy afterward.

The update rule is the **Bellman equation**:

```
Q(s, a) ← Q(s, a) + α × [r + γ × max_a' Q(s', a') − Q(s, a)]
```

Where:
- `α` = learning rate (how much to update per step, e.g., 0.001)
- `r` = reward received after taking action `a`
- `γ` = discount factor (how much future rewards matter, e.g., 0.95)
- `s'` = next state after the action
- `max_a' Q(s', a')` = best possible future Q-value from the next state

### Why Use a Neural Network Instead of a Table?

Classical Q-learning uses a table (Q-table) indexed by (state, action). This requires **finite, discrete states**. Our state is an 8 or 20-dimensional continuous vector — there are infinitely many possible states.

Instead, we use a neural network to **approximate** Q(s, a). The network takes a state vector as input and outputs one Q-value per action. Training the network is equivalent to finding the mapping:

```
state [N features] → [Q(PathA), Q(PathB), Q(Drop)]
```

This is the "Deep" in Deep Q-Network.

### The Basic Architecture

```python
class QNetwork(nn.Module):
    def __init__(self, state_size=8, action_size=3, hidden_size=64):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(state_size, hidden_size),   # 8 → 64
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),  # 64 → 64
            nn.ReLU(),
            nn.Linear(hidden_size, action_size)   # 64 → 3
        )

    def forward(self, x):
        return self.network(x)
```

### The Upgraded Architecture (What This Project Uses)

The upgraded model stacks:
1. **[[LSTM_Memory|LSTM layer]]** — processes a sequence of 10 state snapshots → 128-dimensional hidden state
2. **Shared FC layers** — Linear(128→256) → BatchNorm → ReLU → Dropout(0.2) → Linear(256→128) → BatchNorm → ReLU → Dropout(0.2) → Linear(128→64) → ReLU
3. **[[Dueling_DQN|Dueling heads]]** — splits into Value stream (→1) and Advantage stream (→3), recombines as Q-values

### Two Networks: Online and Target

A critical stability trick in DQN is maintaining **two copies** of the network:

| Network | Role | Updated When? |
|---|---|---|
| Online (Q) network | Used to select actions and compute current Q-values | Every training step |
| Target network | Used to compute the stable Q-value target | Every 100 steps (hard copy) |

Without the target network, the training target `r + γ × max Q(s')` changes every step because the network weights change. This can cause the learning to **chase a moving target**, diverge, and oscillate. The frozen target network provides a stable reference point for computing targets.

---

## 3. Mathematical / Algorithmic Details

### The Training Loss

At each training step, we sample a batch of 64 experiences `(s, a, r, s', done)` from the [[Replay_Buffer|Replay Buffer]] and minimize:

```
L(θ) = E[(Q_target − Q_online(s, a; θ))²]
```

Where:

```
Q_target = r + γ × max_a' Q_target(s', a'; θ⁻)    if not done
Q_target = r                                         if done (terminal state)
```

- `θ` = weights of the online network (being updated)
- `θ⁻` = weights of the target network (frozen, updated periodically)

### Double DQN Improvement

Standard DQN has an **overestimation bias** — `max Q(s', a')` systematically overestimates the true best Q-value because the same network both selects and evaluates the action.

Double DQN fixes this: use the **online network to select** the best action, but use the **target network to evaluate** it:

```
Q_target = r + γ × Q_target(s', argmax_a' Q_online(s', a'; θ); θ⁻)
```

This decouples selection from evaluation and reduces overestimation, leading to more stable and accurate Q-values.

### Gradient Clipping

With LSTM layers, gradients can explode during backpropagation (the famous vanishing/exploding gradient problem). We clip gradients to a maximum norm of 1.0:

```python
torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
```

This prevents individual training updates from taking catastrophically large steps that destabilize the entire model.

### Hyperparameter Table

| Parameter | Value | Why This Value |
|---|---|---|
| `γ` (discount factor) | 0.95 | Balances immediate vs future reward; 0.99 would make very long-horizon plans |
| `ε` initial | 1.0 | Start fully random — explore everything |
| `ε` minimum | 0.01 | Never stop exploring completely — network changes |
| `ε` decay | 0.995 per step | Slow enough to explore broadly before converging |
| Learning rate | 0.001 | Adam optimizer default; small enough to be stable |
| Batch size | 64 | Standard balance of gradient stability vs compute |
| Replay capacity | 10,000 | Large enough to break correlation, small enough to stay in memory |
| Target update freq | 100 steps | Frequent enough to track learning, infrequent enough to provide stability |
| Hidden size | 64→256 | Scaled up for 20-feature input |
| LSTM hidden | 128 | Enough capacity for 10×20 sequence patterns |

---

## 4. Role in Our Project

The DQN agent is the intelligence of the entire system. Every other component exists to serve it or to execute its decisions:

- **[[SDN_Controller|Ryu Controller]]** collects the raw events that become training experiences
- **[[Feature_Engineering|Feature Engineering]]** turns raw OvS stats into a clean state vector the DQN can process
- **[[Replay_Buffer|Replay Buffer]]** stores thousands of past experiences for training
- **[[Reward_Function|Reward Function]]** tells the DQN what "good routing" means
- **[[OpenFlow_Protocol|FlowMod messages]]** execute the DQN's chosen action in the real switch

The DQN sits at the core of the system. When trained, it replaces the static [[Routing_Policies|Shortest Path and ECMP]] policies with a learned, adaptive strategy.

**What it solves specifically:**
- Detects and reacts to elephant flows before they saturate a path
- Distinguishes sensor, video, and elephant traffic and handles each appropriately
- Discovers time-of-day patterns in network usage
- Pre-emptively reroutes flows when it predicts congestion is building

---

## 5. Interconnections

- [[LSTM_Memory]] — the temporal frontend of the upgraded DQN; processes sequence before the Q-value layers
- [[Dueling_DQN]] — the output architecture that separates state value from action advantage
- [[Replay_Buffer]] — experience storage that breaks temporal correlation in training
- [[Reward_Function]] — defines what the DQN optimizes for
- [[State_Space]] — defines what the DQN observes
- [[Exploration_vs_Exploitation]] — ε-greedy strategy governing action selection during training
- [[Training_Process]] — the full end-to-end loop in which the DQN learns
- [[SDN_Controller]] — the entity that calls the DQN for routing decisions

---

## 6. Advanced Insights

### When DQN Works Well

- When the state fully captures the information needed to make a good decision (Markov property is approximately satisfied)
- When episodes are short enough that reward signals are timely (not too delayed)
- When the action space is small and discrete (3 paths = ideal)
- When the environment is stationary enough to converge (network patterns are learnable)

### When DQN Fails

- **Non-stationarity:** If network traffic patterns change dramatically after training (e.g., new device types added), the learned Q-values may be wrong. Online learning or periodic retraining mitigates this.
- **Reward sparsity:** If reward feedback is delayed hours (e.g., SLA violation detected day-later), the Bellman update becomes extremely noisy. Our per-flow reward at flow completion is good — feedback within 30 seconds is tight enough.
- **Overestimation cascades:** Even with Double DQN, overestimation accumulates. Periodic evaluation against a held-out traffic trace helps detect Q-value drift.
- **Large topology:** With 100 switches and 10 paths, the action space grows. Hierarchical RL or per-switch independent agents become necessary.

### The Deadly Triad

Three properties together cause DQN instability:
1. **Off-policy learning** (learning from old experiences not generated by current policy)
2. **Bootstrapping** (using Q-values to estimate other Q-values — circular dependency)
3. **Function approximation** (neural network generalization can spread errors)

Double DQN and the target network reduce the damage, but the triad cannot be fully eliminated without fundamentally changing the algorithm (e.g., to model-based RL).

---

## 7. References for Further Study

- **Deep Q-Network (DQN)** — Mnih et al., "Human-level control through deep reinforcement learning" (2015)
- **Double DQN** — Van Hasselt et al., "Deep Reinforcement Learning with Double Q-learning" (2016)
- **Bellman equation** — Dynamic programming foundations in Sutton & Barto's "Reinforcement Learning: An Introduction"
- **Overestimation in Q-learning** — Thrun & Schwartz, "Issues in using function approximation for RL" (1993)
- **Topics to explore:** Soft Actor-Critic (SAC), TD3, Model-Based RL for network control, Network function virtualization (NFV) with RL
