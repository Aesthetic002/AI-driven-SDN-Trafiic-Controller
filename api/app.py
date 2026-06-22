"""
Phase 4 — Flask REST API

Exposes the DQN agent's live training state for the dashboard and external tools.

Run (standalone mock mode):
    python3 api/app.py --mock

Run (alongside Ryu — controller writes to shared_state automatically):
    python3 api/app.py

Endpoints:
    GET  /api/state       current 20-feature vector with names
    GET  /api/agent       epsilon, steps, reward, loss
    GET  /api/flows       active flows and their assigned paths
    GET  /api/paths       routing decision counters
    GET  /api/metrics     reward + loss + utilisation history
    GET  /api/topology    static network topology (for dashboard)
    GET  /api/snapshot    everything in one call
    GET  /api/compare/current  latest DQN vs baseline comparison snapshot
    GET  /api/compare/history  rolling comparison history
    GET  /api/stream      Server-Sent Events stream (real-time updates)
    POST /api/reset       reset reward accumulator (for experiment runs)
"""

import argparse
import json
import os
import sys
import time
import threading

from flask import Flask, jsonify, Response, request
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from constants import (
    API_HOST, API_PORT, FEATURE_NAMES, RUNTIME_STATE_FILE, REPLAY_BUFFER_FILE,
    IP_SENSOR1, IP_SENSOR2, IP_CAMERA1, IP_EMERG,
    IP_SENSOR3, IP_SENSOR4, IP_CAMERA2, IP_ACTUATOR,
    IP_SENSOR5, IP_SENSOR6, IP_CAMERA3, IP_GATEWAY,
    IP_SERVER1, IP_SERVER2, IP_SERVER3, IP_SERVER4,
    LINK_BW_ACCESS_CORE, LINK_BW_CORE_SERVER_A,
    LINK_BW_CORE_SERVER_B, LINK_BW_CORE_SERVER_C, LINK_BW_CORE_SERVER_D,
    LINK_BW_CROSSLINK, LINK_BW_SERVER,
    LINK_DELAY_S1_S3, LINK_DELAY_S1_S4,
    LINK_DELAY_S2_S3, LINK_DELAY_S2_S4,
    LINK_DELAY_S6_S3, LINK_DELAY_S6_S4,
    LINK_DELAY_S3_S5, LINK_DELAY_S4_S5,
    LINK_DELAY_S3_S7, LINK_DELAY_S4_S7,
    LINK_DELAY_CROSSLINK,
    STATE_DIM, SEQUENCE_LEN, NUM_ACTIONS, ACTION_NAMES, BATCH_SIZE,
    ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C,
    ACTION_PATH_D, ACTION_PATH_E, ACTION_DROP,
)
import api.shared_state as ss

app = Flask(__name__)
CORS(app)   # allow dashboard on :8080 to call API on :5000


# ── Static topology description (used by dashboard) ──────────────────────────

TOPOLOGY = {
    "nodes": [
        # Cluster A (→ S1)
        {"id": "h_sensor1",  "ip": IP_SENSOR1,  "type": "sensor",    "cluster": "A"},
        {"id": "h_sensor2",  "ip": IP_SENSOR2,  "type": "sensor",    "cluster": "A"},
        {"id": "h_camera1",  "ip": IP_CAMERA1,  "type": "camera",    "cluster": "A"},
        {"id": "h_emerg",    "ip": IP_EMERG,    "type": "emergency", "cluster": "A"},
        # Cluster B (→ S2)
        {"id": "h_sensor3",  "ip": IP_SENSOR3,  "type": "sensor",    "cluster": "B"},
        {"id": "h_sensor4",  "ip": IP_SENSOR4,  "type": "sensor",    "cluster": "B"},
        {"id": "h_camera2",  "ip": IP_CAMERA2,  "type": "camera",    "cluster": "B"},
        {"id": "h_actuator", "ip": IP_ACTUATOR, "type": "actuator",  "cluster": "B"},
        # Cluster C (→ S6)
        {"id": "h_sensor5",  "ip": IP_SENSOR5,  "type": "sensor",    "cluster": "C"},
        {"id": "h_sensor6",  "ip": IP_SENSOR6,  "type": "sensor",    "cluster": "C"},
        {"id": "h_camera3",  "ip": IP_CAMERA3,  "type": "camera",    "cluster": "C"},
        {"id": "h_gateway",  "ip": IP_GATEWAY,  "type": "actuator",  "cluster": "C"},
        # Switches
        {"id": "s1", "type": "switch", "role": "access", "cluster": "A"},
        {"id": "s2", "type": "switch", "role": "access", "cluster": "B"},
        {"id": "s3", "type": "switch", "role": "core",   "path": "A/D"},
        {"id": "s4", "type": "switch", "role": "core",   "path": "B/E"},
        {"id": "s5", "type": "switch", "role": "aggregation", "label": "primary"},
        {"id": "s6", "type": "switch", "role": "access", "cluster": "C"},
        {"id": "s7", "type": "switch", "role": "aggregation", "label": "secondary"},
        # Servers
        {"id": "h_server1", "ip": IP_SERVER1, "type": "server", "agg": "primary"},
        {"id": "h_server2", "ip": IP_SERVER2, "type": "server", "agg": "primary"},
        {"id": "h_server3", "ip": IP_SERVER3, "type": "server", "agg": "secondary"},
        {"id": "h_server4", "ip": IP_SERVER4, "type": "server", "agg": "secondary"},
    ],
    "links": [
        # Cluster A host links
        {"source": "h_sensor1",  "target": "s1", "bw": 1,  "delay": "2ms"},
        {"source": "h_sensor2",  "target": "s1", "bw": 1,  "delay": "2ms"},
        {"source": "h_camera1",  "target": "s1", "bw": 10, "delay": "5ms"},
        {"source": "h_emerg",    "target": "s1", "bw": 2,  "delay": "1ms"},
        # Cluster B host links
        {"source": "h_sensor3",  "target": "s2", "bw": 1,  "delay": "2ms"},
        {"source": "h_sensor4",  "target": "s2", "bw": 1,  "delay": "2ms"},
        {"source": "h_camera2",  "target": "s2", "bw": 10, "delay": "5ms"},
        {"source": "h_actuator", "target": "s2", "bw": 2,  "delay": "1ms"},
        # Cluster C host links
        {"source": "h_sensor5",  "target": "s6", "bw": 1,  "delay": "2ms"},
        {"source": "h_sensor6",  "target": "s6", "bw": 1,  "delay": "2ms"},
        {"source": "h_camera3",  "target": "s6", "bw": 10, "delay": "5ms"},
        {"source": "h_gateway",  "target": "s6", "bw": 2,  "delay": "1ms"},
        # Access → core uplinks
        {"source": "s1", "target": "s3", "bw": LINK_BW_ACCESS_CORE, "delay": LINK_DELAY_S1_S3, "path": "A"},
        {"source": "s1", "target": "s4", "bw": LINK_BW_ACCESS_CORE, "delay": LINK_DELAY_S1_S4, "path": "B"},
        {"source": "s2", "target": "s3", "bw": LINK_BW_ACCESS_CORE, "delay": LINK_DELAY_S2_S3, "path": "A"},
        {"source": "s2", "target": "s4", "bw": LINK_BW_ACCESS_CORE, "delay": LINK_DELAY_S2_S4, "path": "B"},
        {"source": "s6", "target": "s3", "bw": LINK_BW_ACCESS_CORE, "delay": LINK_DELAY_S6_S3, "path": "A/D"},
        {"source": "s6", "target": "s4", "bw": LINK_BW_ACCESS_CORE, "delay": LINK_DELAY_S6_S4, "path": "B/E"},
        # Core crosslink
        {"source": "s3", "target": "s4", "bw": LINK_BW_CROSSLINK,     "delay": LINK_DELAY_CROSSLINK, "path": "C"},
        # Core → aggregation
        {"source": "s3", "target": "s5", "bw": LINK_BW_CORE_SERVER_A, "delay": LINK_DELAY_S3_S5, "path": "A"},
        {"source": "s4", "target": "s5", "bw": LINK_BW_CORE_SERVER_B, "delay": LINK_DELAY_S4_S5, "path": "B"},
        {"source": "s3", "target": "s7", "bw": LINK_BW_CORE_SERVER_C, "delay": LINK_DELAY_S3_S7, "path": "D"},
        {"source": "s4", "target": "s7", "bw": LINK_BW_CORE_SERVER_D, "delay": LINK_DELAY_S4_S7, "path": "E"},
        # Aggregation → servers
        {"source": "s5", "target": "h_server1", "bw": LINK_BW_SERVER, "delay": "1ms"},
        {"source": "s5", "target": "h_server2", "bw": LINK_BW_SERVER, "delay": "1ms"},
        {"source": "s7", "target": "h_server3", "bw": LINK_BW_SERVER, "delay": "1ms"},
        {"source": "s7", "target": "h_server4", "bw": LINK_BW_SERVER, "delay": "1ms"},
    ],
}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return """<!doctype html><meta charset=utf-8>
<title>AI-SDN API</title>
<style>body{font-family:monospace;background:#0f1117;color:#e2e8f0;padding:40px}
a{color:#6366f1}h1{margin-bottom:24px}</style>
<h1>AI-SDN REST API</h1>
<p><a href="http://localhost:8080" target="_blank">→ Open Dashboard (port 8080)</a></p>
<br>
<p><b>Endpoints:</b></p>
<ul style="line-height:2">
  <li><a href="/api/snapshot">/api/snapshot</a> — everything in one call</li>
  <li><a href="/api/state">/api/state</a> — current 20-feature state vector</li>
  <li><a href="/api/agent">/api/agent</a> — epsilon, steps, reward, loss</li>
  <li><a href="/api/paths">/api/paths</a> — routing decision counts</li>
  <li><a href="/api/flows">/api/flows</a> — active flows</li>
  <li><a href="/api/metrics">/api/metrics</a> — reward/loss/util history</li>
  <li><a href="/api/topology">/api/topology</a> — static network graph</li>
  <li><a href="/api/compare/current">/api/compare/current</a> — latest DQN vs baseline</li>
  <li><a href="/api/compare/history">/api/compare/history</a> — comparison history</li>
  <li>/api/stream — Server-Sent Events (used by dashboard)</li>
</ul>"""


@app.get("/api/state")
def get_state():
    snap = ss.snapshot()
    return jsonify({
        "features": dict(zip(
            snap["feature_names"] or FEATURE_NAMES,
            snap["current_state"],
        )),
        "raw":        snap["current_state"],
        "last_update": snap["last_update"],
    })


@app.get("/api/agent")
def get_agent():
    snap = ss.snapshot()
    return jsonify({
        "epsilon":      snap["epsilon"],
        "learn_steps":  snap["learn_steps"],
        "total_reward": snap["total_reward"],
        "last_loss":    snap["last_loss"],
        "uptime_s":     snap["uptime_s"],
    })


@app.get("/api/flows")
def get_flows():
    return jsonify(ss.snapshot()["active_flows"])


@app.get("/api/paths")
def get_paths():
    return jsonify(ss.snapshot()["path_counts"])


@app.get("/api/metrics")
def get_metrics():
    snap = ss.snapshot()
    return jsonify({
        "reward_history": snap["reward_history"],
        "loss_history":   snap["loss_history"],
        "util_history":   snap["util_history"],
    })


@app.get("/api/topology")
def get_topology():
    return jsonify(TOPOLOGY)


@app.get("/api/snapshot")
def get_snapshot():
    snap = ss.snapshot()
    snap["topology"] = TOPOLOGY
    return jsonify(snap)


@app.get("/api/compare/current")
def get_compare_current():
    return jsonify(ss.snapshot().get("comparison", {}))


@app.get("/api/compare/history")
def get_compare_history():
    snap = ss.snapshot()
    return jsonify({
        "comparison": snap.get("comparison", {}),
        "history": snap.get("compare_history", []),
    })


# ── Real DQN inference (used by the Simulation Lab "Real model" mode) ─────────
# Serves the ACTUAL trained Dueling-LSTM-DQN. The Lab builds a 26-feature state
# from its simulation and POSTs the 10-step sequence here; we return the model's
# greedy action (argmax Q) — the converged policy, exploration disabled.
_DQN = {"agent": None, "trained": False, "err": None, "tried": False}

def _weights_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "model_weights.pth")

def _load_dqn():
    """Lazy, one-shot load so the API still starts instantly in mock mode and
    degrades gracefully if torch or the weights file are missing."""
    if _DQN["tried"]:
        return _DQN
    _DQN["tried"] = True
    try:
        import torch  # noqa: F401
        from agent.dqn_agent import DQNAgent
        agent = DQNAgent()
        wp = _weights_path()
        if os.path.exists(wp):
            agent.load(wp)                       # read works even if file is root-owned
            _DQN["trained"] = agent.steps > 0
        # warm-start the replay buffer so real gradient steps begin promptly
        # instead of after a 64-tick cold fill (best-effort).
        try:
            if os.path.exists(REPLAY_BUFFER_FILE):
                agent.load_buffer(REPLAY_BUFFER_FILE)
        except Exception:
            pass
        # NOTE: keep online net in train() mode (its default) so learn() trains
        # correctly and action selection matches the real controller exactly.
        _DQN["agent"] = agent
    except Exception as exc:   # torch missing, bad weights, etc.
        _DQN["err"] = str(exc)
    return _DQN


@app.get("/api/dqn/status")
def dqn_status():
    d = _load_dqn()
    if d["agent"] is None:
        return jsonify({"available": False, "error": d["err"],
                        "hint": "Install torch and/or run train.py to create model_weights.pth"})
    a = d["agent"]
    return jsonify({
        "available": True, "trained": d["trained"],
        "steps": a.steps, "epsilon": round(a.epsilon, 4),
        "state_dim": STATE_DIM, "seq_len": SEQUENCE_LEN, "num_actions": NUM_ACTIONS,
        "weights_exists": os.path.exists(_weights_path()),
    })


@app.post("/api/dqn/decide")
def dqn_decide():
    d = _load_dqn()
    if d["agent"] is None:
        return jsonify({"available": False, "error": d["err"]})
    body = request.get_json(force=True, silent=True) or {}
    seq = body.get("seq")
    if not isinstance(seq, list) or not seq or not isinstance(seq[0], list):
        return jsonify({"available": True, "error": "expected 'seq' = list of state vectors"}), 400
    try:
        import numpy as np
        import torch
        a = d["agent"]
        # accept a single state too → repeat to fill the sequence window
        if not isinstance(seq[0][0] if seq[0] else None, (int, float)):
            return jsonify({"available": True, "error": "state vectors must be numeric"}), 400
        if len(seq[0]) != STATE_DIM:
            return jsonify({"available": True,
                            "error": f"each state must have {STATE_DIM} features, got {len(seq[0])}"}), 400
        x = torch.tensor(np.array(seq, dtype=np.float32)).unsqueeze(0)  # (1, seq, dim)
        with torch.no_grad():
            q = a.online(x)
        action = int(q.argmax(dim=1).item())
        qv = [round(float(v), 4) for v in q.squeeze(0).tolist()]
    except Exception as exc:
        return jsonify({"available": True, "error": str(exc)}), 500
    return jsonify({
        "available": True, "action": action, "action_name": ACTION_NAMES.get(action, "?"),
        "q": qv, "trained": d["trained"], "steps": a.steps, "epsilon": round(a.epsilon, 4),
    })


# ── Live training driven by the Simulation Lab ───────────────────────────────
# The browser sim is the ENVIRONMENT; the real DQNAgent here is the LEARNER.
# Each tick the Lab posts the observed state; we train the real network on the
# previous transition (real reward fn + real gradient step + epsilon decay) and
# return the next epsilon-greedy action. Every metric is pushed to shared_state
# so EVERY dashboard tab reflects this session live — it is real training.
_COMP_KEYS = ("latency", "reliability", "throughput", "fairness")
_SIM = {"active": False}

def _sim_reset(meta):
    _SIM.update({
        "active": True, "meta": meta or {},
        "prev_seq": None, "prev_action": None,
        "prev_base": None, "prev_base_action": None,
        "dqn_total": 0.0, "base_total": 0.0,
        "cd": {k: 0.0 for k in _COMP_KEYS}, "cb": {k: 0.0 for k in _COMP_KEYS},
        "counts": {}, "base_counts": {},
    })

def _named_pc(c):
    return {"PATH_A": c.get("A", 0), "PATH_B": c.get("B", 0), "PATH_C": c.get("C", 0),
            "PATH_D": c.get("D", 0), "PATH_E": c.get("E", 0), "DROP": c.get("DROP", 0)}

def _actions_pc(c):
    return {ACTION_PATH_A: c.get("A", 0), ACTION_PATH_B: c.get("B", 0), ACTION_PATH_C: c.get("C", 0),
            ACTION_PATH_D: c.get("D", 0), ACTION_PATH_E: c.get("E", 0), ACTION_DROP: c.get("DROP", 0)}

def _sim_comparison():
    dqn, base = _SIM["dqn_total"], _SIM["base_total"]
    delta = dqn - base
    cd, cb = _SIM["cd"], _SIM["cb"]
    def comp(k):
        dv, bv = cd[k], cb[k]
        return {"dqn": round(dv, 3), "baseline": round(bv, 3), "delta": round(dv - bv, 3),
                "winner": "dqn" if dv > bv else "baseline" if bv > dv else "tie"}
    return {
        "enabled": True, "routing_mode": "dqn",
        "baseline_policy": _SIM["meta"].get("baseline", "shortest_path"),
        "dqn_reward": round(dqn, 3), "baseline_reward": round(base, 3),
        "reward_delta": round(delta, 3),
        "reward_delta_pct": round(delta / max(abs(base), 0.001) * 100, 2),
        "winner": "dqn" if delta >= 0 else "baseline",
        "dqn_path_counts": _named_pc(_SIM["counts"]),
        "baseline_path_counts": _named_pc(_SIM["base_counts"]),
        "components": {k: comp(k) for k in _COMP_KEYS},
    }


@app.post("/api/sim/start")
def sim_start():
    d = _load_dqn()
    if d["agent"] is None:
        return jsonify({"available": False, "error": d["err"]})
    a = d["agent"]
    a.episode_count += 1
    try:
        a.save(_weights_path())          # best-effort: may be root-owned from sudo training
    except Exception:
        pass
    _sim_reset(request.get_json(force=True, silent=True) or {})
    return jsonify({"ok": True, "episode": a.episode_count, "epsilon": round(a.epsilon, 4),
                    "steps": a.steps, "trained": d["trained"]})


@app.post("/api/sim/stop")
def sim_stop():
    _SIM["active"] = False
    d = _load_dqn()
    if d["agent"] is not None:
        try:
            d["agent"].save(_weights_path())
        except Exception:
            pass
    return jsonify({"ok": True})


@app.post("/api/sim/tick")
def sim_tick():
    d = _load_dqn()
    if d["agent"] is None:
        return jsonify({"available": False, "error": d["err"]})
    a = d["agent"]
    if not _SIM.get("active"):
        _sim_reset({})
    body = request.get_json(force=True, silent=True) or {}
    seq = body.get("seq")
    if not isinstance(seq, list) or not seq or len(seq[-1]) != STATE_DIM:
        return jsonify({"available": True, "error": f"seq must be a list of {STATE_DIM}-feature vectors"}), 400

    from agent.dqn_agent import compute_reward_components
    self_counts = body.get("counts", {}) or {}
    base_seq = body.get("base_seq")
    base_action = body.get("base_action")
    base_counts = body.get("base_counts", {}) or {}
    flows = body.get("flows", []) or []
    _SIM["counts"] = self_counts
    _SIM["base_counts"] = base_counts

    loss = None
    # 1) train the real network on the previous transition (real reward + grad step)
    if _SIM["prev_seq"] is not None:
        comp = compute_reward_components(_SIM["prev_seq"][-1], _SIM["prev_action"], seq[-1])
        a.store(_SIM["prev_seq"], _SIM["prev_action"], comp["total"], seq, done=False)
        loss = a.learn()
        _SIM["dqn_total"] += comp["total"]
        for k in _COMP_KEYS:
            _SIM["cd"][k] += comp[k]
    # shadow baseline reward for the comparison tab
    if base_seq is not None and base_action is not None and _SIM["prev_base"] is not None:
        cb = compute_reward_components(_SIM["prev_base"][-1], _SIM["prev_base_action"], base_seq[-1])
        _SIM["base_total"] += cb["total"]
        for k in _COMP_KEYS:
            _SIM["cb"][k] += cb[k]

    # 2) epsilon-greedy action for the current state (this is what gets applied next)
    action = a.select_action(seq)

    # 3) broadcast to shared_state → every tab updates from this real session
    now = time.time()
    cur = seq[-1]
    ss.push_controller_timestamp(now)
    ss.push_state(cur, FEATURE_NAMES)
    ss.push_agent(a.epsilon, a.steps, _SIM["dqn_total"], loss, episode_count=a.episode_count)
    ss.push_path_counts(_actions_pc(self_counts))
    ss.push_util(sum(cur[:7]) / 7.0)
    ss.push_comparison(_sim_comparison())
    ss.push_flow_decisions(flows)
    with ss._lock:
        ss._state["active_flows"] = {
            f.get("flow", f"flow{i}"): {
                "action": -1, "path": f.get("dqn_path", "?"),
                "age_s": f.get("age_s", 0), "priority": f.get("priority", False),
            } for i, f in enumerate(flows)
        }

    # 4) remember transition + persist periodically (best-effort)
    _SIM["prev_seq"], _SIM["prev_action"] = seq, action
    _SIM["prev_base"], _SIM["prev_base_action"] = base_seq, base_action
    if a.steps and a.steps % 50 == 0:
        try: a.save(_weights_path())
        except Exception: pass
        try: a.save_buffer(REPLAY_BUFFER_FILE)
        except Exception: pass

    return jsonify({
        "available": True, "action": action, "action_name": ACTION_NAMES.get(action, "?"),
        "epsilon": round(a.epsilon, 4), "steps": a.steps, "loss": loss,
        "episode": a.episode_count, "buffer": len(a.replay), "batch": BATCH_SIZE,
        "dqn_total": round(_SIM["dqn_total"], 3), "base_total": round(_SIM["base_total"], 3),
    })


@app.post("/api/reset")
def post_reset():
    ss._state["total_reward"]   = 0.0
    ss._state["reward_history"].clear()
    ss._state["loss_history"].clear()
    ss._state["util_history"].clear()
    ss._state["compare_history"].clear()
    return jsonify({"status": "reset", "t": time.time()})


@app.get("/api/stream")
def event_stream():
    """
    Server-Sent Events — pushes a snapshot every 2 seconds.
    Dashboard subscribes with:  const es = new EventSource('/api/stream')
    """
    def generate():
        while True:
            data = json.dumps(ss.snapshot())
            yield f"data: {data}\n\n"
            time.sleep(2)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ── Mock data pump (for testing without Ryu) ──────────────────────────────────

def _mock_pump():
    """Pushes synthetic data into shared_state when running in --mock mode."""
    import math, random
    from constants import (ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C,
                           ACTION_PATH_D, ACTION_PATH_E, ACTION_DROP)
    t = 0
    while True:
        if _SIM.get("active"):          # a live Sim-Lab training session owns the state
            time.sleep(1); continue
        # Simulate oscillating utilisation (7 core links + 6 new S6/S7 links)
        util = [abs(math.sin(t * 0.1 + i * 0.5)) * 0.8 for i in range(7)]
        util6 = [abs(math.sin(t * 0.12 + i * 0.6)) * 0.6 for i in range(6)]  # indices 20-25
        state = (util
                 + [random.uniform(0, 0.5)] * 3   # flow counts A/B/C
                 + [random.uniform(0, 0.05)] * 2  # loss
                 + [random.uniform(0, 0.1)]  * 2  # jitter
                 + [random.uniform(0, 1)]    * 2  # bytes
                 + [time.time() % 86400 / 86400,  # ToD
                    random.uniform(-0.1, 0.1),     # trend
                    float(t % 30 < 5),             # priority flag
                    float(max(util) > 0.8)]        # congestion
                 + util6)                          # features 20-25        # congestion

        ss.push_state(state, FEATURE_NAMES)
        ss.push_agent(
            epsilon=max(0.01, 1.0 - t * 0.002),
            learn_steps=t,
            total_reward=t * 0.3 + random.gauss(0, 0.5),
            loss=random.uniform(0.001, 0.5) if t > 10 else None,
            episode_count=1,
        )
        mock_path_counts = {
            ACTION_PATH_A: random.randint(0, 5),
            ACTION_PATH_B: random.randint(0, 3),
            ACTION_PATH_C: random.randint(0, 1),
            ACTION_PATH_D: random.randint(0, 3),
            ACTION_PATH_E: random.randint(0, 2),
            ACTION_DROP:   random.randint(0, 1),
        }
        ss.push_path_counts(mock_path_counts)
        dqn_reward = t * 0.35 + random.gauss(0, 0.4)
        baseline_reward = t * 0.22 + random.gauss(0, 0.5)
        delta = dqn_reward - baseline_reward

        # Per-component reward breakdown — DQN tends to do better on latency
        # and fairness once it learns; baseline matches throughput/reliability.
        learn_factor = min(1.0, t / 200.0)   # ramps up over first ~7 minutes
        def _comp(d_base, b_base, d_jitter=0.04, advantage=0.10):
            d = d_base * t + random.gauss(0, d_jitter * t)
            b = b_base * t + random.gauss(0, d_jitter * t)
            d += advantage * learn_factor * t
            return round(d, 3), round(b, 3), round(d - b, 3)

        d_lat,  b_lat,  e_lat  = _comp(0.16, 0.13, advantage=0.06)
        d_rel,  b_rel,  e_rel  = _comp(0.10, 0.10, advantage=0.02)
        d_thr,  b_thr,  e_thr  = _comp(0.06, 0.05, advantage=0.01)
        d_fair, b_fair, e_fair = _comp(0.03, 0.02, advantage=0.04)

        def _winner(a, b):
            return "dqn" if a > b else "baseline" if b > a else "tie"

        ss.push_comparison({
            "enabled": True,
            "routing_mode": "dqn",
            "baseline_policy": "least_utilized",
            "dqn_reward": round(dqn_reward, 3),
            "baseline_reward": round(baseline_reward, 3),
            "reward_delta": round(delta, 3),
            "reward_delta_pct": round((delta / max(abs(baseline_reward), 0.001)) * 100.0, 2),
            "winner": "dqn" if delta >= 0 else "baseline",
            "dqn_path_counts": {
                "PATH_A": mock_path_counts[ACTION_PATH_A],
                "PATH_B": mock_path_counts[ACTION_PATH_B],
                "PATH_C": mock_path_counts[ACTION_PATH_C],
                "PATH_D": mock_path_counts[ACTION_PATH_D],
                "PATH_E": mock_path_counts[ACTION_PATH_E],
                "DROP":   mock_path_counts[ACTION_DROP],
            },
            "baseline_path_counts": {
                "PATH_A": random.randint(0, 5),
                "PATH_B": random.randint(0, 4),
                "PATH_C": random.randint(0, 2),
                "PATH_D": random.randint(0, 3),
                "PATH_E": random.randint(0, 2),
                "DROP":   random.randint(0, 2),
            },
            "components": {
                "latency":     {"dqn": d_lat,  "baseline": b_lat,  "delta": e_lat,  "winner": _winner(d_lat,  b_lat)},
                "reliability": {"dqn": d_rel,  "baseline": b_rel,  "delta": e_rel,  "winner": _winner(d_rel,  b_rel)},
                "throughput":  {"dqn": d_thr,  "baseline": b_thr,  "delta": e_thr,  "winner": _winner(d_thr,  b_thr)},
                "fairness":    {"dqn": d_fair, "baseline": b_fair, "delta": e_fair, "winner": _winner(d_fair, b_fair)},
            },
        })
        ss.push_util(sum(util[:4]) / 4)
        all_paths = ["PATH_A", "PATH_B", "PATH_C", "PATH_D", "PATH_E"]
        mock_flows = [
            {"flow": "10.0.0.1->10.0.0.9",  "dqn_path": random.choice(all_paths),
             "baseline_path": random.choice(all_paths), "priority": False, "age_s": t % 30},
            {"flow": "10.0.0.3->10.0.0.9",  "dqn_path": random.choice(all_paths),
             "baseline_path": random.choice(all_paths), "priority": False, "age_s": t % 20},
            {"flow": "10.0.0.11->10.0.0.15","dqn_path": random.choice(["PATH_D", "PATH_E"]),
             "baseline_path": random.choice(all_paths), "priority": False, "age_s": t % 25},
            {"flow": "10.0.0.4->10.0.0.10", "dqn_path": random.choice(all_paths),
             "baseline_path": "PATH_B",     "priority": True,  "age_s": t % 15},
        ]
        for f in mock_flows:
            f["agreed"] = f["dqn_path"] == f["baseline_path"]
        ss.push_flow_decisions(mock_flows)
        t += 1
        time.sleep(2)


# ── File pump (production — reads Ryu's JSON file) ───────────────────────────

def _file_pump():
    """Reads RUNTIME_STATE_FILE written by Ryu and pushes into shared_state."""
    from constants import (ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C,
                           ACTION_PATH_D, ACTION_PATH_E, ACTION_DROP)
    last_mtime = 0
    while True:
        if _SIM.get("active"):          # a live Sim-Lab training session owns the state
            time.sleep(1); continue
        try:
            mtime = os.path.getmtime(RUNTIME_STATE_FILE)
            if mtime > last_mtime:
                last_mtime = mtime
                with open(RUNTIME_STATE_FILE) as f:
                    d = json.load(f)
                ss.push_state(d.get("state", [0.0]*26),
                              d.get("feature_names", FEATURE_NAMES))
                ss.push_agent(d.get("epsilon", 1.0), d.get("learn_steps", 0),
                              d.get("total_reward", 0.0), d.get("last_loss"),
                              episode_count=d.get("episode_count"))
                pc = d.get("path_counts", {})
                ss.push_path_counts({
                    ACTION_PATH_A: pc.get("PATH_A", 0),
                    ACTION_PATH_B: pc.get("PATH_B", 0),
                    ACTION_PATH_C: pc.get("PATH_C", 0),
                    ACTION_PATH_D: pc.get("PATH_D", 0),
                    ACTION_PATH_E: pc.get("PATH_E", 0),
                    ACTION_DROP:   pc.get("DROP",   0),
                })
                ss.push_util(d.get("avg_util", 0.0))
                ss.push_comparison(d.get("comparison", {}))
                ss.push_flow_decisions(d.get("flow_decisions", []))
                ss.push_controller_timestamp(d.get("t", 0))
                with ss._lock:
                    ss._state["active_flows"] = d.get("active_flows", {})
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        time.sleep(1)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true",
                        help="Inject synthetic data (no Ryu needed)")
    parser.add_argument("--host", default=API_HOST)
    parser.add_argument("--port", type=int, default=API_PORT)
    args = parser.parse_args()

    if args.mock:
        print("[api] Mock mode — synthetic data every 2s")
        threading.Thread(target=_mock_pump, daemon=True).start()
    else:
        print(f"[api] Production mode — reading {RUNTIME_STATE_FILE}")
        threading.Thread(target=_file_pump, daemon=True).start()

    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"[api] Listening on http://{args.host}:{args.port}{'  [debug/reload on]' if debug else ''}")
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=debug, debug=debug)
