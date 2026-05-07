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
    API_HOST, API_PORT, FEATURE_NAMES, RUNTIME_STATE_FILE,
    IP_SENSOR1, IP_SENSOR2, IP_CAMERA1, IP_EMERG,
    IP_SENSOR3, IP_SENSOR4, IP_CAMERA2, IP_ACTUATOR,
    IP_SERVER1, IP_SERVER2,
    LINK_BW_ACCESS_CORE, LINK_BW_CORE_SERVER_A,
    LINK_BW_CORE_SERVER_B, LINK_BW_CROSSLINK, LINK_BW_SERVER,
    LINK_DELAY_S1_S3, LINK_DELAY_S1_S4,
    LINK_DELAY_S2_S3, LINK_DELAY_S2_S4,
    LINK_DELAY_S3_S5, LINK_DELAY_S4_S5,
    LINK_DELAY_CROSSLINK,
)
import api.shared_state as ss

app = Flask(__name__)
CORS(app)   # allow dashboard on :8080 to call API on :5000


# ── Static topology description (used by dashboard) ──────────────────────────

TOPOLOGY = {
    "nodes": [
        {"id": "h_sensor1",  "ip": IP_SENSOR1,  "type": "sensor",    "cluster": "A"},
        {"id": "h_sensor2",  "ip": IP_SENSOR2,  "type": "sensor",    "cluster": "A"},
        {"id": "h_camera1",  "ip": IP_CAMERA1,  "type": "camera",    "cluster": "A"},
        {"id": "h_emerg",    "ip": IP_EMERG,    "type": "emergency", "cluster": "A"},
        {"id": "h_sensor3",  "ip": IP_SENSOR3,  "type": "sensor",    "cluster": "B"},
        {"id": "h_sensor4",  "ip": IP_SENSOR4,  "type": "sensor",    "cluster": "B"},
        {"id": "h_camera2",  "ip": IP_CAMERA2,  "type": "camera",    "cluster": "B"},
        {"id": "h_actuator", "ip": IP_ACTUATOR, "type": "actuator",  "cluster": "B"},
        {"id": "s1",  "type": "switch", "role": "access"},
        {"id": "s2",  "type": "switch", "role": "access"},
        {"id": "s3",  "type": "switch", "role": "core",   "path": "A"},
        {"id": "s4",  "type": "switch", "role": "core",   "path": "B"},
        {"id": "s5",  "type": "switch", "role": "aggregation"},
        {"id": "h_server1", "ip": IP_SERVER1, "type": "server"},
        {"id": "h_server2", "ip": IP_SERVER2, "type": "server"},
    ],
    "links": [
        {"source": "h_sensor1",  "target": "s1", "bw": 1,                    "delay": "2ms"},
        {"source": "h_sensor2",  "target": "s1", "bw": 1,                    "delay": "2ms"},
        {"source": "h_camera1",  "target": "s1", "bw": 10,                   "delay": "5ms"},
        {"source": "h_emerg",    "target": "s1", "bw": 2,                    "delay": "1ms"},
        {"source": "h_sensor3",  "target": "s2", "bw": 1,                    "delay": "2ms"},
        {"source": "h_sensor4",  "target": "s2", "bw": 1,                    "delay": "2ms"},
        {"source": "h_camera2",  "target": "s2", "bw": 10,                   "delay": "5ms"},
        {"source": "h_actuator", "target": "s2", "bw": 2,                    "delay": "1ms"},
        {"source": "s1", "target": "s3", "bw": LINK_BW_ACCESS_CORE,  "delay": LINK_DELAY_S1_S3, "path": "A"},
        {"source": "s1", "target": "s4", "bw": LINK_BW_ACCESS_CORE,  "delay": LINK_DELAY_S1_S4, "path": "B"},
        {"source": "s2", "target": "s3", "bw": LINK_BW_ACCESS_CORE,  "delay": LINK_DELAY_S2_S3, "path": "A"},
        {"source": "s2", "target": "s4", "bw": LINK_BW_ACCESS_CORE,  "delay": LINK_DELAY_S2_S4, "path": "B"},
        {"source": "s3", "target": "s5", "bw": LINK_BW_CORE_SERVER_A,"delay": LINK_DELAY_S3_S5, "path": "A"},
        {"source": "s4", "target": "s5", "bw": LINK_BW_CORE_SERVER_B,"delay": LINK_DELAY_S4_S5, "path": "B"},
        {"source": "s3", "target": "s4", "bw": LINK_BW_CROSSLINK,    "delay": LINK_DELAY_CROSSLINK, "path": "C"},
        {"source": "s5", "target": "h_server1", "bw": LINK_BW_SERVER,"delay": "1ms"},
        {"source": "s5", "target": "h_server2", "bw": LINK_BW_SERVER,"delay": "1ms"},
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
    from constants import ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C, ACTION_DROP
    t = 0
    while True:
        # Simulate oscillating utilisation
        util = [abs(math.sin(t * 0.1 + i * 0.5)) * 0.8 for i in range(7)]
        state = (util
                 + [random.uniform(0, 0.5)] * 3   # flow counts
                 + [random.uniform(0, 0.05)] * 2  # loss
                 + [random.uniform(0, 0.1)]  * 2  # jitter
                 + [random.uniform(0, 1)]    * 2  # bytes
                 + [time.time() % 86400 / 86400,  # ToD
                    random.uniform(-0.1, 0.1),     # trend
                    float(t % 30 < 5),             # priority flag
                    float(max(util) > 0.8)])        # congestion

        ss.push_state(state, FEATURE_NAMES)
        ss.push_agent(
            epsilon=max(0.01, 1.0 - t * 0.002),
            learn_steps=t,
            total_reward=t * 0.3 + random.gauss(0, 0.5),
            loss=random.uniform(0.001, 0.5) if t > 10 else None,
        )
        mock_path_counts = {
            ACTION_PATH_A: random.randint(0, 5),
            ACTION_PATH_B: random.randint(0, 3),
            ACTION_PATH_C: random.randint(0, 1),
            ACTION_DROP:   random.randint(0, 1),
        }
        ss.push_path_counts(mock_path_counts)
        dqn_reward = t * 0.35 + random.gauss(0, 0.4)
        baseline_reward = t * 0.22 + random.gauss(0, 0.5)
        delta = dqn_reward - baseline_reward
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
                "DROP": mock_path_counts[ACTION_DROP],
            },
            "baseline_path_counts": {
                "PATH_A": random.randint(0, 5),
                "PATH_B": random.randint(0, 4),
                "PATH_C": random.randint(0, 2),
                "DROP": random.randint(0, 2),
            },
        })
        ss.push_util(sum(util[:4]) / 4)
        t += 1
        time.sleep(2)


# ── File pump (production — reads Ryu's JSON file) ───────────────────────────

def _file_pump():
    """Reads RUNTIME_STATE_FILE written by Ryu and pushes into shared_state."""
    from constants import ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C, ACTION_DROP
    last_mtime = 0
    while True:
        try:
            mtime = os.path.getmtime(RUNTIME_STATE_FILE)
            if mtime > last_mtime:
                last_mtime = mtime
                with open(RUNTIME_STATE_FILE) as f:
                    d = json.load(f)
                ss.push_state(d.get("state", [0.0]*20),
                              d.get("feature_names", FEATURE_NAMES))
                ss.push_agent(d.get("epsilon", 1.0), d.get("learn_steps", 0),
                              d.get("total_reward", 0.0), d.get("last_loss"))
                pc = d.get("path_counts", {})
                ss.push_path_counts({
                    ACTION_PATH_A: pc.get("PATH_A", 0),
                    ACTION_PATH_B: pc.get("PATH_B", 0),
                    ACTION_PATH_C: pc.get("PATH_C", 0),
                    ACTION_DROP:   pc.get("DROP",   0),
                })
                ss.push_util(d.get("avg_util", 0.0))
                ss.push_comparison(d.get("comparison", {}))
                # push flows directly into shared state
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
