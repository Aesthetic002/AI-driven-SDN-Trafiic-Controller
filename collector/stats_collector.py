"""
Phase 2 — Statistics Collector

Polls all 5 Open vSwitch nodes every STATS_INTERVAL seconds and produces
the 20-feature state vector consumed by the DQN agent.

Features tracked:
  - 7 link utilizations  (S1→S3, S1→S4, S2→S3, S2→S4, S3→S5, S4→S5, S3↔S4)
  - 3 active-flow counts (Path A / B / C)
  - 2 packet-loss rates  (Path A / B)
  - 2 jitter estimates   (Path A / B)
  - 2 cumulative bytes   (Path A / B)
  - 4 scalar signals     (time-of-day, util trend, priority flag, congestion flag)

Usage:
    python3 collector/stats_collector.py              # live (Mininet must be up)
    python3 collector/stats_collector.py --mock       # synthetic, no Mininet needed
    python3 collector/stats_collector.py --once       # one snapshot + exit

Public API (imported by api/app.py and controller/ryu_controller.py):
    get_state() -> list[float]   # length == STATE_DIM (20)
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from constants import (
        SWITCHES, STATS_INTERVAL, STATE_DIM, FEATURE_NAMES,
        # S1 uplink ports
        S1_PORT_CORE_A, S1_PORT_CORE_B,
        # S2 uplink ports
        S2_PORT_CORE_A, S2_PORT_CORE_B,
        # S3/S4/S5 ports
        S3_PORT_FROM_S1, S3_PORT_FROM_S2, S3_PORT_TO_S5, S3_PORT_CROSSLINK,
        S4_PORT_FROM_S1, S4_PORT_FROM_S2, S4_PORT_TO_S5, S4_PORT_CROSSLINK,
        S5_PORT_FROM_S3, S5_PORT_FROM_S4,
        # Link capacities for normalisation
        LINK_BW_ACCESS_CORE, LINK_BW_CORE_SERVER_A,
        LINK_BW_CORE_SERVER_B, LINK_BW_CROSSLINK,
        # DQN actions (to classify flows by output port)
        ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C,
    )
except ImportError:
    SWITCHES = ["s1", "s2", "s3", "s4", "s5"]
    STATS_INTERVAL = 2.0; STATE_DIM = 20
    FEATURE_NAMES = [f"feat_{i}" for i in range(STATE_DIM)]
    S1_PORT_CORE_A = 5; S1_PORT_CORE_B = 6
    S2_PORT_CORE_A = 5; S2_PORT_CORE_B = 6
    S3_PORT_FROM_S1 = 1; S3_PORT_FROM_S2 = 2
    S3_PORT_TO_S5 = 3;   S3_PORT_CROSSLINK = 4
    S4_PORT_FROM_S1 = 1; S4_PORT_FROM_S2 = 2
    S4_PORT_TO_S5 = 3;   S4_PORT_CROSSLINK = 4
    S5_PORT_FROM_S3 = 1; S5_PORT_FROM_S4 = 2
    LINK_BW_ACCESS_CORE = 20; LINK_BW_CORE_SERVER_A = 50
    LINK_BW_CORE_SERVER_B = 100; LINK_BW_CROSSLINK = 50
    ACTION_PATH_A = 0; ACTION_PATH_B = 1; ACTION_PATH_C = 2


# ── OvS helpers ───────────────────────────────────────────────────────────────

def _ovs(*args) -> str:
    try:
        r = subprocess.run(list(args), capture_output=True, text=True, timeout=3)
        return r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _dump_ports(sw: str) -> str:
    return _ovs("ovs-ofctl", "dump-ports", sw)


def _dump_flows(sw: str) -> str:
    return _ovs("ovs-ofctl", "dump-flows", sw)


# ── Parsers ───────────────────────────────────────────────────────────────────

PortStats = dict[int, dict]   # port_no → {rx_bytes, tx_bytes, rx_pkts, tx_pkts, rx_drop, tx_drop}


def parse_port_stats(raw: str) -> PortStats:
    """
    Parse `ovs-ofctl dump-ports` output.

    Example lines:
      port  1: rx pkts=100, bytes=9000, drop=0, errs=0, frame=0, over=0, crc=0
               tx pkts=80,  bytes=7000, drop=0, errs=0, coll=0
    """
    ports: PortStats = {}
    cur: Optional[int] = None

    for line in raw.splitlines():
        m = re.match(r"\s*port\s+(\d+|LOCAL):", line)
        if m:
            raw_p = m.group(1)
            cur = -1 if raw_p == "LOCAL" else int(raw_p)
            ports[cur] = dict(rx_bytes=0, tx_bytes=0,
                              rx_pkts=0,  tx_pkts=0,
                              rx_drop=0,  tx_drop=0)

        if cur is None:
            continue

        rx = re.search(r"rx pkts=(\d+), bytes=(\d+), drop=(\d+)", line)
        if rx:
            ports[cur]["rx_pkts"]  = int(rx.group(1))
            ports[cur]["rx_bytes"] = int(rx.group(2))
            ports[cur]["rx_drop"]  = int(rx.group(3))

        tx = re.search(r"tx pkts=(\d+), bytes=(\d+), drop=(\d+)", line)
        if tx:
            ports[cur]["tx_pkts"]  = int(tx.group(1))
            ports[cur]["tx_bytes"] = int(tx.group(2))
            ports[cur]["tx_drop"]  = int(tx.group(3))

    return ports


def parse_flow_stats(raw: str) -> list[dict]:
    """
    Parse `ovs-ofctl dump-flows` output.
    Returns list of {out_port, n_packets, n_bytes, duration, priority, dscp}.
    """
    flows = []
    for line in raw.splitlines():
        if "actions=" not in line:
            continue

        f: dict = {}

        for key, pat in [
            ("n_packets", r"n_packets=(\d+)"),
            ("n_bytes",   r"n_bytes=(\d+)"),
            ("priority",  r"priority=(\d+)"),
        ]:
            m = re.search(pat, line)
            f[key] = int(m.group(1)) if m else 0

        m = re.search(r"duration=([\d.]+)s", line)
        f["duration"] = float(m.group(1)) if m else 0.0

        m = re.search(r"actions=.*output:(\d+)", line)
        f["out_port"] = int(m.group(1)) if m else -1

        m = re.search(r"nw_tos=(\d+)", line)
        f["dscp"] = (int(m.group(1)) >> 2) if m else 0

        flows.append(f)

    return flows


# ── State computation ─────────────────────────────────────────────────────────

class StatsCollector:
    """
    Stateful collector that tracks rolling deltas and jitter history.
    """

    def __init__(self):
        self._prev: dict[str, PortStats] = {}
        self._prev_time: float = 0.0
        self._prev_avg_util: float = 0.0
        self._jitter_hist: dict[str, list[float]] = {"A": [], "B": [], "C": []}

    # ── Public ────────────────────────────────────────────────────────────────

    def get_state(self) -> list[float]:
        """Poll OvS and return the 20-float state vector."""
        now = time.time()
        dt  = max(now - self._prev_time, 1e-3)

        port_stats: dict[str, PortStats] = {
            sw: parse_port_stats(_dump_ports(sw)) for sw in SWITCHES
        }
        # Flows inspected on s3 (Path A/C) and s4 (Path B) since they carry
        # all inter-cluster traffic after the Ryu controller installs FlowMods.
        flows_s3 = parse_flow_stats(_dump_flows("s3"))
        flows_s4 = parse_flow_stats(_dump_flows("s4"))

        state = self._compute(port_stats, flows_s3, flows_s4, dt, now)

        self._prev      = port_stats
        self._prev_time = now
        return state

    def get_state_dict(self) -> dict:
        return dict(zip(FEATURE_NAMES, self.get_state()))

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compute(
        self,
        ports: dict[str, PortStats],
        flows_s3: list[dict],
        flows_s4: list[dict],
        dt: float,
        now: float,
    ) -> list[float]:

        s1 = ports.get("s1", {}); ps1 = self._prev.get("s1", {})
        s2 = ports.get("s2", {}); ps2 = self._prev.get("s2", {})
        s3 = ports.get("s3", {}); ps3 = self._prev.get("s3", {})
        s4 = ports.get("s4", {}); ps4 = self._prev.get("s4", {})

        # ── Features 0-6: link utilizations ──────────────────────────────────
        # Access → core uplinks (20 Mbps each)
        util_s1_s3 = _clamp(_port_mbps(s1, ps1, S1_PORT_CORE_A, dt) / LINK_BW_ACCESS_CORE)
        util_s1_s4 = _clamp(_port_mbps(s1, ps1, S1_PORT_CORE_B, dt) / LINK_BW_ACCESS_CORE)
        util_s2_s3 = _clamp(_port_mbps(s2, ps2, S2_PORT_CORE_A, dt) / LINK_BW_ACCESS_CORE)
        util_s2_s4 = _clamp(_port_mbps(s2, ps2, S2_PORT_CORE_B, dt) / LINK_BW_ACCESS_CORE)

        # Core → server (asymmetric capacities)
        util_s3_s5 = _clamp(_port_mbps(s3, ps3, S3_PORT_TO_S5,     dt) / LINK_BW_CORE_SERVER_A)
        util_s4_s5 = _clamp(_port_mbps(s4, ps4, S4_PORT_TO_S5,     dt) / LINK_BW_CORE_SERVER_B)
        util_xl    = _clamp(_port_mbps(s3, ps3, S3_PORT_CROSSLINK,  dt) / LINK_BW_CROSSLINK)

        # ── Features 7-9: active flows per path ──────────────────────────────
        # Path A: flows whose output port on S3 goes toward S5 (port 3)
        # Path C: flows whose output port on S3 goes toward S4 (port 4, cross-link)
        # Path B: flows on S4 whose output port goes toward S5 (port 3)
        flows_a = sum(1 for f in flows_s3 if f["out_port"] == S3_PORT_TO_S5)
        flows_c = sum(1 for f in flows_s3 if f["out_port"] == S3_PORT_CROSSLINK)
        flows_b = sum(1 for f in flows_s4 if f["out_port"] == S4_PORT_TO_S5)

        # ── Features 10-11: packet loss per path ─────────────────────────────
        loss_a = _loss_rate(s3, S3_PORT_TO_S5)
        loss_b = _loss_rate(s4, S4_PORT_TO_S5)

        # ── Features 12-13: jitter estimates ─────────────────────────────────
        jitter_a = self._jitter("A", util_s3_s5)
        jitter_b = self._jitter("B", util_s4_s5)

        # ── Features 14-15: cumulative bytes per path (normalized) ───────────
        bytes_a = _clamp(s3.get(S3_PORT_TO_S5,    {}).get("tx_bytes", 0) / 1e7)
        bytes_b = _clamp(s4.get(S4_PORT_TO_S5,    {}).get("tx_bytes", 0) / 1e7)

        # ── Feature 16: time of day ───────────────────────────────────────────
        t   = datetime.fromtimestamp(now)
        tod = (t.hour * 3600 + t.minute * 60 + t.second) / 86400.0

        # ── Feature 17: utilization trend ────────────────────────────────────
        all_utils = [util_s1_s3, util_s1_s4, util_s2_s3, util_s2_s4,
                     util_s3_s5, util_s4_s5, util_xl]
        avg_util  = sum(all_utils) / len(all_utils)
        trend     = _clamp((avg_util - self._prev_avg_util) * 5.0, lo=-1.0)
        self._prev_avg_util = avg_util

        # ── Feature 18: priority flag ─────────────────────────────────────────
        all_flows = flows_s3 + flows_s4
        priority_flag = 1.0 if any(f.get("dscp", 0) >= 34 for f in all_flows) else 0.0

        # ── Feature 19: congestion flag ───────────────────────────────────────
        congestion = 1.0 if any(u > 0.8 for u in all_utils) else 0.0

        return [
            util_s1_s3,             # 0
            util_s1_s4,             # 1
            util_s2_s3,             # 2
            util_s2_s4,             # 3
            util_s3_s5,             # 4
            util_s4_s5,             # 5
            util_xl,                # 6
            _clamp(flows_a / 20.0), # 7
            _clamp(flows_b / 20.0), # 8
            _clamp(flows_c / 20.0), # 9
            loss_a,                 # 10
            loss_b,                 # 11
            jitter_a,               # 12
            jitter_b,               # 13
            bytes_a,                # 14
            bytes_b,                # 15
            tod,                    # 16
            trend,                  # 17
            priority_flag,          # 18
            congestion,             # 19
        ]

    def _jitter(self, path: str, util: float) -> float:
        hist = self._jitter_hist[path]
        hist.append(util)
        if len(hist) > 10:
            hist.pop(0)
        if len(hist) < 2:
            return 0.0
        mean = sum(hist) / len(hist)
        var  = sum((x - mean) ** 2 for x in hist) / len(hist)
        return _clamp(math.sqrt(var) * 50.0 / 50.0)   # std-dev → ms equivalent


# ── Utility functions ─────────────────────────────────────────────────────────

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _port_mbps(curr: PortStats, prev: PortStats, port: int, dt: float) -> float:
    cb = curr.get(port, {}).get("tx_bytes", 0)
    pb = prev.get(port, {}).get("tx_bytes", 0)
    return (max(cb - pb, 0) * 8) / (dt * 1e6)


def _loss_rate(ports: PortStats, port: int) -> float:
    p  = ports.get(port, {})
    rx = p.get("rx_pkts", 0)
    tx = p.get("tx_pkts", 0)
    dr = p.get("rx_drop", 0) + p.get("tx_drop", 0)
    return _clamp(dr / max(rx + tx, 1))


# ── Mock mode ─────────────────────────────────────────────────────────────────

def _mock_state() -> list[float]:
    """Synthetic plausible state — no OvS connection needed."""
    import random
    t   = datetime.now()
    tod = (t.hour * 3600 + t.minute * 60 + t.second) / 86400.0
    ua  = random.uniform(0.1, 0.9)   # S3 path (Path A) — simulate congestion spikes
    ub  = random.uniform(0.05, 0.6)  # S4 path (Path B)
    uxl = random.uniform(0.0, 0.2)   # cross-link — usually idle
    return [
        ua * 0.9,                        # 0  link_util_s1_s3
        ub * 0.7,                        # 1  link_util_s1_s4
        ua * 0.6,                        # 2  link_util_s2_s3
        ub * 0.5,                        # 3  link_util_s2_s4
        ua,                              # 4  link_util_s3_s5
        ub,                              # 5  link_util_s4_s5
        uxl,                             # 6  link_util_crosslink
        random.uniform(0.0, 0.5),        # 7  active_flows_path_a
        random.uniform(0.0, 0.4),        # 8  active_flows_path_b
        random.uniform(0.0, 0.1),        # 9  active_flows_path_c (rare)
        max(0.0, ua - 0.75) * 0.2,       # 10 packet_loss_path_a
        0.0,                             # 11 packet_loss_path_b
        random.uniform(0.0, 0.3),        # 12 jitter_path_a
        random.uniform(0.0, 0.15),       # 13 jitter_path_b
        random.uniform(0.0, 0.5),        # 14 bytes_path_a
        random.uniform(0.0, 0.4),        # 15 bytes_path_b
        tod,                             # 16 time_of_day
        random.uniform(-0.1, 0.1),       # 17 util_trend
        1.0 if ua > 0.7 else 0.0,        # 18 priority_flag
        1.0 if ua > 0.8 or ub > 0.8 else 0.0,  # 19 congestion_flag
    ]


# ── Module-level singleton ────────────────────────────────────────────────────

_collector  = StatsCollector()
_mock_mode  = False


def get_state() -> list[float]:
    """
    Public API — called by api/app.py and controller/ryu_controller.py.
    Returns a list of STATE_DIM (20) normalised floats.
    """
    return _mock_state() if _mock_mode else _collector.get_state()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="IoT SDN stats collector")
    parser.add_argument("--mock",     action="store_true")
    parser.add_argument("--once",     action="store_true")
    parser.add_argument("--interval", type=float, default=STATS_INTERVAL)
    args = parser.parse_args()

    global _mock_mode
    _mock_mode = args.mock

    mode = "MOCK" if args.mock else "LIVE"
    print(f"[stats_collector] {mode} mode | interval={args.interval}s", flush=True)

    if args.once:
        state = get_state()
        print(json.dumps(dict(zip(FEATURE_NAMES, state)), indent=2))
        assert len(state) == STATE_DIM, f"Expected {STATE_DIM} features, got {len(state)}"
        print(f"\n[OK] {STATE_DIM} features verified.")
        return

    header = f"{'n':<4}  " + "  ".join(f"{n[:14]:<14}" for n in FEATURE_NAMES[:5]) + "  ..."
    print(header, flush=True)
    i = 0
    while True:
        t0    = time.time()
        state = get_state()
        row   = f"{i:<4}  " + "  ".join(f"{v:<14.4f}" for v in state[:5])
        row  += f"  ... [{(time.time()-t0)*1000:.0f}ms]"
        print(row, flush=True)
        i += 1
        remaining = args.interval - (time.time() - t0)
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    main()
