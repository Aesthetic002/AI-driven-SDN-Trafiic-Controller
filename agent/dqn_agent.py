"""
Phase 3 — Dueling LSTM-DQN agent for SDN path selection.

Architecture:
  Input  : (batch, seq_len, STATE_DIM) float32 tensor
  LSTM   : hidden_dim=128, 2 layers, dropout=0.2
  Dueling: V(s) + A(s,a) - mean(A)  →  Q(s,a)  shape (batch, NUM_ACTIONS)

Public API:
  agent = DQNAgent()
  action = agent.select_action(state_seq)   # state_seq: list[list[float]] len=seq_len
  agent.store(state_seq, action, reward, next_state_seq, done)
  loss   = agent.learn()                    # None until replay buffer has BATCH_SIZE entries
  agent.save(path) / agent.load(path)
"""

import os
import pickle
import sys
import random
from collections import deque

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from constants import (
    STATE_DIM, NUM_ACTIONS, SEQUENCE_LEN,
    REPLAY_CAPACITY, BATCH_SIZE, GAMMA, LR,
    EPS_START, EPS_END, EPS_DECAY,
    TARGET_SYNC, GRAD_CLIP_NORM,
    R_LATENCY, R_RELIABILITY, R_THROUGHPUT, R_FAIRNESS, R_PRIORITY_MUL,
    ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C,
    ACTION_PATH_D, ACTION_PATH_E, ACTION_DROP,
    ACTION_NAMES,
)

DEVICE = torch.device("cpu")


# ── Neural network ────────────────────────────────────────────────────────────

class DuelingLSTM(nn.Module):
    """Dueling LSTM-DQN: shared LSTM trunk → separate value and advantage heads."""

    def __init__(self, state_dim: int = STATE_DIM, hidden_dim: int = 128,
                 num_layers: int = 2, num_actions: int = NUM_ACTIONS,
                 dropout: float = 0.2):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_size=state_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        # Value stream: scalar V(s)
        self.value_head = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

        # Advantage stream: A(s, a) for each action
        self.adv_head = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, num_actions),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (batch, seq_len, state_dim) → Q: (batch, num_actions)"""
        lstm_out, _ = self.lstm(x)
        last = lstm_out[:, -1, :]          # take final time-step
        v = self.value_head(last)          # (batch, 1)
        a = self.adv_head(last)            # (batch, num_actions)
        # Dueling combination: Q = V + (A - mean(A))
        q = v + (a - a.mean(dim=1, keepdim=True))
        return q


# ── Replay buffer ─────────────────────────────────────────────────────────────

class ReplayBuffer:
    def __init__(self, capacity: int = REPLAY_CAPACITY):
        self.buf = deque(maxlen=capacity)

    def push(self, state_seq, action, reward, next_state_seq, done):
        self.buf.append((
            np.array(state_seq, dtype=np.float32),
            int(action),
            float(reward),
            np.array(next_state_seq, dtype=np.float32),
            bool(done),
        ))

    def sample(self, batch_size: int = BATCH_SIZE):
        batch = random.sample(self.buf, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        return (
            torch.tensor(np.array(states),      dtype=torch.float32, device=DEVICE),
            torch.tensor(actions,               dtype=torch.long,    device=DEVICE),
            torch.tensor(rewards,               dtype=torch.float32, device=DEVICE),
            torch.tensor(np.array(next_states), dtype=torch.float32, device=DEVICE),
            torch.tensor(dones,                 dtype=torch.float32, device=DEVICE),
        )

    def __len__(self):
        return len(self.buf)


# ── Reward shaping ────────────────────────────────────────────────────────────

def compute_reward_components(state: list[float], action: int,
                              next_state: list[float]) -> dict:
    """
    Reward breakdown for diagnostics + per-component DQN-vs-baseline comparison.

    Returns a dict with these keys (all floats, already weighted by R_*):
      total       — final clipped scalar (matches compute_reward)
      latency     — R_LATENCY     * latency_r     [* priority]
      reliability — R_RELIABILITY * reliability_r [* priority]
      throughput  — R_THROUGHPUT  * throughput_r  [* priority]
      fairness    — R_FAIRNESS    * fairness_r    [* priority]

    For ACTION_DROP the components are zero (no path chosen) and the total is
    +0.1 if congested, else −1.0 — same as compute_reward.
    """
    util_s3_s5   = next_state[4]
    util_s4_s5   = next_state[5]
    loss_path_a  = next_state[10]
    loss_path_b  = next_state[11]
    bytes_path_a = next_state[14]
    bytes_path_b = next_state[15]
    priority_flag    = next_state[18]
    congestion_flag  = next_state[19]
    util_s3_s7   = next_state[22] if len(next_state) > 22 else 0.0
    util_s4_s7   = next_state[23] if len(next_state) > 23 else 0.0

    zero = {"total": 0.0, "latency": 0.0, "reliability": 0.0,
            "throughput": 0.0, "fairness": 0.0}

    if action == ACTION_DROP:
        zero["total"] = 0.1 if congestion_flag else -1.0
        return zero

    if action == ACTION_PATH_A:
        latency_r     = 1.0 - util_s3_s5
        reliability_r = 1.0 - loss_path_a
        throughput_r  = bytes_path_a
        fairness_r    = 1.0 - abs(util_s3_s5 - util_s4_s5)
    elif action == ACTION_PATH_B:
        latency_r     = 1.0 - util_s4_s5
        reliability_r = 1.0 - loss_path_b
        throughput_r  = bytes_path_b
        fairness_r    = 1.0 - abs(util_s3_s5 - util_s4_s5)
    elif action == ACTION_PATH_C:
        latency_r     = 0.5 * (1.0 - util_s3_s5) + 0.5 * (1.0 - util_s4_s5) - 0.1
        reliability_r = 0.5 * (1.0 - loss_path_a) + 0.5 * (1.0 - loss_path_b)
        throughput_r  = 0.5 * (bytes_path_a + bytes_path_b)
        fairness_r    = 1.0 - abs(util_s3_s5 - util_s4_s5)
    elif action == ACTION_PATH_D:
        # Via S3 → S7: uses secondary aggregation, slightly higher latency than A
        latency_r     = 1.0 - util_s3_s7 - 0.05   # 5% penalty vs primary
        reliability_r = 1.0 - loss_path_a
        throughput_r  = bytes_path_a * 0.9          # 75Mbps cap vs 50Mbps but normalized
        fairness_r    = 1.0 - abs(util_s3_s7 - util_s4_s7)
    elif action == ACTION_PATH_E:
        # Via S4 → S7: secondary high-BW path
        latency_r     = 1.0 - util_s4_s7 - 0.05
        reliability_r = 1.0 - loss_path_b
        throughput_r  = bytes_path_b * 0.95         # 80Mbps cap
        fairness_r    = 1.0 - abs(util_s3_s7 - util_s4_s7)
    else:
        return zero
    mul = R_PRIORITY_MUL if priority_flag else 1.0

    lat_w   = R_LATENCY     * latency_r     * mul
    rel_w   = R_RELIABILITY * reliability_r * mul
    thr_w   = R_THROUGHPUT  * throughput_r  * mul
    fair_w  = R_FAIRNESS    * fairness_r    * mul

    total = float(np.clip(lat_w + rel_w + thr_w + fair_w, -1.0, 5.0))
    return {
        "total":       total,
        "latency":     float(lat_w),
        "reliability": float(rel_w),
        "throughput":  float(thr_w),
        "fairness":    float(fair_w),
    }


def compute_reward(state: list[float], action: int, next_state: list[float]) -> float:
    """Backwards-compatible scalar reward — calls compute_reward_components."""
    return compute_reward_components(state, action, next_state)["total"]


# ── Agent ─────────────────────────────────────────────────────────────────────

class DQNAgent:
    def __init__(self):
        self.online = DuelingLSTM().to(DEVICE)
        self.target = DuelingLSTM().to(DEVICE)
        self.target.load_state_dict(self.online.state_dict())
        self.target.eval()

        self.optimizer = torch.optim.Adam(self.online.parameters(), lr=LR)
        self.replay    = ReplayBuffer()

        self.epsilon       = EPS_START
        self.steps         = 0
        self.episode_count = 0

    # ── Action selection ──────────────────────────────────────────────────────

    def select_action(self, state_seq: list[list[float]]) -> int:
        """Epsilon-greedy action selection. state_seq shape: (seq_len, STATE_DIM)."""
        if random.random() < self.epsilon:
            return random.randrange(NUM_ACTIONS)
        x = torch.tensor(
            np.array(state_seq, dtype=np.float32),
            device=DEVICE,
        ).unsqueeze(0)                          # (1, seq_len, state_dim)
        with torch.no_grad():
            q = self.online(x)
        return int(q.argmax(dim=1).item())

    # ── Experience storage ────────────────────────────────────────────────────

    def store(self, state_seq, action, reward, next_state_seq, done):
        self.replay.push(state_seq, action, reward, next_state_seq, done)

    # ── Learning step ─────────────────────────────────────────────────────────

    def learn(self) -> float | None:
        """Sample a mini-batch and do one gradient step. Returns loss or None."""
        if len(self.replay) < BATCH_SIZE:
            return None

        states, actions, rewards, next_states, dones = self.replay.sample()

        # Double-DQN: online selects, target evaluates
        with torch.no_grad():
            next_actions = self.online(next_states).argmax(dim=1)
            next_q = self.target(next_states).gather(1, next_actions.unsqueeze(1)).squeeze(1)
            targets = rewards + GAMMA * next_q * (1.0 - dones)

        current_q = self.online(states).gather(1, actions.unsqueeze(1)).squeeze(1)
        loss = F.smooth_l1_loss(current_q, targets)

        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.online.parameters(), GRAD_CLIP_NORM)
        self.optimizer.step()

        self.steps += 1
        self.epsilon = max(EPS_END, self.epsilon * EPS_DECAY)

        if self.steps % TARGET_SYNC == 0:
            self.target.load_state_dict(self.online.state_dict())

        return float(loss.item())

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str):
        torch.save({
            "online":        self.online.state_dict(),
            "target":        self.target.state_dict(),
            "optimizer":     self.optimizer.state_dict(),
            "epsilon":       self.epsilon,
            "steps":         self.steps,
            "episode_count": self.episode_count,
        }, path)

    def load(self, path: str):
        ckpt = torch.load(path, map_location=DEVICE)
        self.online.load_state_dict(ckpt["online"])
        self.target.load_state_dict(ckpt["target"])
        self.optimizer.load_state_dict(ckpt["optimizer"])
        self.epsilon       = ckpt["epsilon"]
        self.steps         = ckpt["steps"]
        self.episode_count = ckpt.get("episode_count", 0)

    def save_buffer(self, path: str):
        """Persist the replay buffer to disk so experiences survive between runs."""
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(list(self.replay.buf), f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)

    def load_buffer(self, path: str):
        """Restore a previously saved replay buffer."""
        with open(path, "rb") as f:
            entries = pickle.load(f)
        self.replay.buf = deque(entries, maxlen=self.replay.buf.maxlen)
        return len(self.replay.buf)


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("DQNAgent smoke test")
    agent = DQNAgent()

    # Fake state sequence: seq_len=10, 20 features each
    def rand_seq():
        return [[random.random() for _ in range(STATE_DIM)] for _ in range(SEQUENCE_LEN)]

    # Fill replay buffer past BATCH_SIZE
    for _ in range(BATCH_SIZE + 10):
        s  = rand_seq()
        ns = rand_seq()
        a  = agent.select_action(s)
        r  = compute_reward(s[-1], a, ns[-1])
        agent.store(s, a, r, ns, done=False)

    loss = agent.learn()
    print(f"  epsilon : {agent.epsilon:.4f}")
    print(f"  steps   : {agent.steps}")
    print(f"  loss    : {loss:.6f}")

    # Verify action names
    for i in range(NUM_ACTIONS):
        q_vals = agent.online(
            torch.tensor(rand_seq(), dtype=torch.float32).unsqueeze(0)
        )
        a = int(q_vals.argmax())
        print(f"  sample action: {ACTION_NAMES[a]}")

    agent.save("/tmp/dqn_test.pt")
    agent.load("/tmp/dqn_test.pt")
    print("  save/load: OK")
    print("Smoke test passed.")
