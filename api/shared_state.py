"""
Thread-safe shared state written by the Ryu controller and read by the Flask API.

Both processes import this module. Ryu calls the write helpers; Flask reads via
the snapshot() function which returns a deep copy safe to serialise as JSON.
"""

import threading
import time
from collections import deque

_lock = threading.Lock()

# ── Live state ────────────────────────────────────────────────────────────────
_state = {
    # Current 20-feature vector (list[float])
    "current_state":    [0.0] * 20,
    "feature_names":    [],

    # DQN agent metrics
    "epsilon":          1.0,
    "learn_steps":      0,
    "total_reward":     0.0,
    "last_loss":        None,

    # Path routing counters
    "path_counts": {"PATH_A": 0, "PATH_B": 0, "PATH_C": 0, "DROP": 0},

    # Active flows  { "src->dst": {"action": int, "path": str, "age_s": float} }
    "active_flows":     {},

    # Rolling history (last 200 data points each)
    "reward_history":   deque(maxlen=200),
    "loss_history":     deque(maxlen=200),
    "util_history":     deque(maxlen=200),   # avg link util per tick

    # Timestamps
    "last_update":      None,
    "start_time":       time.time(),
}


# ── Write API (called by Ryu controller) ──────────────────────────────────────

def push_state(feature_vector: list[float], feature_names: list[str]):
    with _lock:
        _state["current_state"] = list(feature_vector)
        _state["feature_names"] = list(feature_names)
        _state["last_update"]   = time.time()


def push_agent(epsilon: float, learn_steps: int, total_reward: float,
               loss: float | None):
    with _lock:
        _state["epsilon"]      = epsilon
        _state["learn_steps"]  = learn_steps
        _state["total_reward"] = total_reward
        _state["last_loss"]    = loss
        if loss is not None:
            _state["loss_history"].append({"t": time.time(), "loss": loss})
        _state["reward_history"].append({"t": time.time(), "reward": total_reward})


def push_path_counts(counts: dict[int, int]):
    from constants import ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C, ACTION_DROP
    with _lock:
        _state["path_counts"] = {
            "PATH_A": counts.get(ACTION_PATH_A, 0),
            "PATH_B": counts.get(ACTION_PATH_B, 0),
            "PATH_C": counts.get(ACTION_PATH_C, 0),
            "DROP":   counts.get(ACTION_DROP,   0),
        }


def push_flows(flow_table: dict):
    """flow_table: {(src, dst): FlowEntry}"""
    from constants import ACTION_NAMES
    now = time.time()
    flows = {}
    for (src, dst), entry in flow_table.items():
        flows[f"{src}->{dst}"] = {
            "action":    entry.action,
            "path":      ACTION_NAMES.get(entry.action, "?"),
            "age_s":     round(now - entry.start_time, 1),
            "priority":  entry.is_priority,
        }
    with _lock:
        _state["active_flows"] = flows


def push_util(avg_util: float):
    with _lock:
        _state["util_history"].append({"t": time.time(), "util": avg_util})


# ── Read API (called by Flask) ─────────────────────────────────────────────────

def snapshot() -> dict:
    """Return a JSON-serialisable deep copy of the current state."""
    with _lock:
        uptime = time.time() - _state["start_time"]
        return {
            "current_state":  _state["current_state"],
            "feature_names":  _state["feature_names"],
            "epsilon":        round(_state["epsilon"], 4),
            "learn_steps":    _state["learn_steps"],
            "total_reward":   round(_state["total_reward"], 3),
            "last_loss":      round(_state["last_loss"], 6) if _state["last_loss"] else None,
            "path_counts":    dict(_state["path_counts"]),
            "active_flows":   dict(_state["active_flows"]),
            "reward_history": list(_state["reward_history"]),
            "loss_history":   list(_state["loss_history"]),
            "util_history":   list(_state["util_history"]),
            "last_update":    _state["last_update"],
            "uptime_s":       round(uptime, 1),
        }
