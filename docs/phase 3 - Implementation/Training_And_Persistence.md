# Training and Persistence
### How the DQN learns, how weights accumulate across runs, and what gets saved

---

## Table of Contents

- [[#Training Loop Overview|Training Loop Overview]]
- [[#The Stats Loop Greenlet|The Stats Loop Greenlet]]
- [[#Double-DQN Update|Double-DQN Update]]
- [[#Epsilon-Greedy Exploration|Epsilon-Greedy Exploration]]
- [[#Target Network Sync|Target Network Sync]]
- [[#Gradient Clipping|Gradient Clipping]]
- [[#What Gets Saved|What Gets Saved]]
- [[#Persistence Across Runs|Persistence Across Runs]]
- [[#Replay Buffer|Replay Buffer]]
- [[#How Many Steps Per Run|How Many Steps Per Run]]
- [[#Training Progress Indicators|Training Progress Indicators]]
- [[#Resetting Training|Resetting Training]]

---

## Training Loop Overview

The training loop runs as a Ryu **greenlet** (cooperative coroutine) inside the controller process. It fires every `STATS_INTERVAL = 2.0` seconds and performs one full observation–store–learn cycle:

```
Every 2 seconds:
  1. Poll OvS (ovs-ofctl dump-ports + dump-flows on all 5 switches)
  2. Compute new_state (20 floats)
  3. Overwrite flow-count and priority features with controller's own data
  4. Append new_state to state_buffer (rolling window of 10 states)
  5. For each active flow in flow_table:
       reward = compute_reward(prev_state, action, new_state)
       agent.store(state_seq, action, reward, new_state_seq, done=False)
  6. loss = agent.learn()
       → if replay buffer < 64 transitions: returns None, nothing happens
       → else: one Double-DQN gradient step
  7. agent.save(model_weights.pth)
  8. agent.save_buffer(/tmp/sdn_replay_buffer.pkl)
  9. Write /tmp/sdn_runtime_state.json (for Flask API)
  10. Push to api.shared_state (in-process, for Flask running in same process)
```

Flows also trigger a `done=True` store when they expire (FlowRemoved event):
```
FlowRemoved event:
  → reward = compute_reward(entry.state_seq[-1], entry.action, last_state)
  → agent.store(entry.state_seq, action, reward, last_state_seq, done=True)
```

---

## The Stats Loop Greenlet

Ryu uses **eventlet** (green threads) internally. `hub.spawn(_stats_loop)` launches the training loop as a cooperative greenlet that shares the same OS thread as the OpenFlow event handlers.

`hub.sleep(STATS_INTERVAL)` yields control back to eventlet's scheduler, allowing PacketIn and FlowRemoved events to be processed while the loop waits.

This means the training loop and the packet handling are **not truly concurrent** — they interleave cooperatively. This is fine because:
1. OvS handles all packet forwarding in kernel space; PacketIn only fires for *new* flows
2. A gradient step takes < 5ms on CPU; the 2-second interval is not tight

---

## Double-DQN Update

Standard DQN overestimates Q-values because it uses the same network for both action selection and evaluation. Double-DQN fixes this:

```python
# Step 1: online network selects best next action
next_actions = online_net(next_states).argmax(dim=1)

# Step 2: target network evaluates that action (independent estimation)
next_q = target_net(next_states).gather(1, next_actions.unsqueeze(1)).squeeze(1)

# Step 3: Bellman target
targets = rewards + GAMMA * next_q * (1.0 - dones)

# Step 4: current Q for the taken action
current_q = online_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)

# Step 5: Huber loss (less sensitive to outliers than MSE)
loss = F.smooth_l1_loss(current_q, targets)
```

**GAMMA = 0.99** — agent values future rewards almost as much as immediate ones. This is appropriate for network routing where a good path now prevents congestion for the next several 2-second intervals.

---

## Epsilon-Greedy Exploration

```python
EPS_START = 1.0    # 100% random at the beginning
EPS_END   = 0.01   # minimum 1% random forever
EPS_DECAY = 0.995  # multiplied after each gradient step
```

After each gradient step:
```python
epsilon = max(EPS_END, epsilon * EPS_DECAY)
```

Decay progress:

| Steps | Epsilon |
|-------|---------|
| 0 | 1.000 |
| 100 | 0.605 |
| 200 | 0.366 |
| 300 | 0.221 |
| 500 | 0.082 |
| 690 | 0.031 |
| 900 | ~0.011 |
| 920+ | 0.010 (floor) |

At 1 gradient step per 2 seconds, reaching epsilon = 0.01 takes approximately 920 steps = **1840 seconds = ~30 minutes of continuous training**.

Epsilon persists across runs in `model_weights.pth`, so a second run picks up where the first stopped.

---

## Target Network Sync

```python
TARGET_SYNC = 100   # steps
```

Every 100 gradient steps, the target network's weights are hard-copied from the online network:

```python
if self.steps % TARGET_SYNC == 0:
    self.target.load_state_dict(self.online.state_dict())
```

The target network is kept frozen between syncs. This stabilises training — without it, the Q-value targets shift every step, causing oscillation or divergence.

---

## Gradient Clipping

```python
GRAD_CLIP_NORM = 1.0
nn.utils.clip_grad_norm_(online.parameters(), GRAD_CLIP_NORM)
```

After `loss.backward()`, all gradient vectors are rescaled so the total L2 norm does not exceed 1.0. Prevents exploding gradients, especially important in early training when Q-values are random.

---

## What Gets Saved

### `model_weights.pth`

Saved by `agent.save(path)` every stats cycle (every 2 seconds):

```python
torch.save({
    "online":    online.state_dict(),    # DuelingLSTM weights
    "target":    target.state_dict(),    # Target network weights
    "optimizer": optimizer.state_dict(), # Adam momentum, lr state
    "epsilon":   self.epsilon,           # Current exploration rate
    "steps":     self.steps,             # Total gradient steps taken
}, path)
```

Location: `<project_root>/model_weights.pth`

### `/tmp/sdn_replay_buffer.pkl`

Saved by `agent.save_buffer(path)` every stats cycle, using atomic write:

```python
tmp = path + ".tmp"
with open(tmp, "wb") as f:
    pickle.dump(list(self.replay.buf), f, protocol=pickle.HIGHEST_PROTOCOL)
os.replace(tmp, path)   # atomic — no partial writes visible
```

Contains up to `REPLAY_CAPACITY = 10,000` transitions. Each transition:
```
(state_seq, action, reward, next_state_seq, done)
where state_seq: np.float32 array (10, 20)
```

Approximate file size: 10,000 × (2 × 10 × 20 × 4 bytes) ≈ **16 MB**

### `/tmp/sdn_runtime_state.json`

Written atomically by `_write_state_file()` after every stats cycle. Read by the Flask `_file_pump` thread. Contains:
- Current 20-feature state vector
- epsilon, learn_steps, total_reward, last_loss
- path_counts, active_flows
- feature_names

---

## Persistence Across Runs

When Ryu starts:

```python
if os.path.exists(WEIGHTS_PATH):
    agent.load(WEIGHTS_PATH)
    # Restores: online weights, target weights, optimizer state, epsilon, steps

if os.path.exists(REPLAY_BUFFER_FILE):
    n = agent.load_buffer(REPLAY_BUFFER_FILE)
    # Restores: up to 10,000 past transitions
    # If n >= BATCH_SIZE (64), first stats cycle immediately runs a gradient step
```

This means:
- **Epsilon** continues decaying from its last value — the agent gets less random over time
- **Replay buffer** starts pre-filled — learning begins immediately instead of waiting for 64 new flows
- **Optimizer momentum** is restored — Adam does not reset to cold-start behaviour

### Accumulation timeline (example)

| Run | Duration | Learn steps | Epsilon after | Buffer size |
|-----|----------|-------------|--------------|-------------|
| 1 | 4 min | 8 | 0.96 | ~150 |
| 2 | 4 min | 16 | 0.92 | ~300 |
| 5 | 4 min | 40 | 0.82 | ~750 |
| 20 | 4 min | 160 | 0.45 | ~3,000 |
| 50 | 4 min | 400 | 0.13 | ~7,500 |
| 70+ | 4 min | 560 | ~0.06 | 10,000 (cap) |

---

## Replay Buffer

**Capacity:** `REPLAY_CAPACITY = 10,000` transitions (circular deque — oldest entries dropped when full)

**Batch size:** `BATCH_SIZE = 64` (sampled uniformly at random)

Each replay buffer entry stores:
```
state_seq:      np.float32 (10, 20)   — 10 state snapshots before action
action:         int                   — 0=Path A, 1=Path B, 2=Path C, 3=Drop
reward:         float                 — shaped reward [-1.0, 5.0]
next_state_seq: np.float32 (10, 20)   — 10 state snapshots after action
done:           bool                  — True if flow expired (FlowRemoved)
```

**Experience generation rate:**
- Each active flow generates one transition per stats cycle (every 2s)
- With 4–10 flows active, that is 4–10 transitions per 2s = 2–5 per second
- Buffer fills to 64 in ~15–30 seconds; first gradient step happens then

---

## How Many Steps Per Run

| Phase secs | Total secs | Stats cycles | Flows active | Approx transitions | Approx gradient steps |
|------------|-----------|-------------|-------------|-------------------|-----------------------|
| 10 | 40 | 20 | 2–8 | 100–160 | 2–3 |
| 60 | 240 | 120 | 4–12 | 500–1,440 | 8–22 |
| 300 | 1200 | 600 | 4–12 | 2,400–7,200 | 37–112 |
| 600 | 2400 | 1200 | 4–15 | 4,800–18,000 | 75–280 |

Each gradient step takes < 5ms on CPU. Total GPU/CPU compute per run is negligible.

---

## Training Progress Indicators

**Good signs:**
- Loss decreasing over many steps (may fluctuate within a run, look at the trend)
- Epsilon below 0.5 — agent is mostly exploiting learned policy
- Path A and Path B both being used — agent is load-balancing
- Path C appearing rarely — reserved for overflow conditions
- Drop count near zero — agent not giving up unnecessarily

**Concerning signs:**
- Loss > 10 and not decreasing — try more runs (needs more experience)
- Epsilon still 1.0 — replay buffer has not reached 64 yet (short runs)
- Only one path always chosen — may need more varied traffic phases

---

## Resetting Training

To start completely from scratch:

```bash
rm -f model_weights.pth /tmp/sdn_replay_buffer.pkl
```

To keep weights but clear the replay buffer (retrain from existing policy, fresh experience):

```bash
rm -f /tmp/sdn_replay_buffer.pkl
```

To keep the replay buffer but reset weights (warm buffer, cold policy):

```bash
rm -f model_weights.pth
```

See also: [[State_And_Reward]] · [[Modules_Reference]] · [[Architecture]]
