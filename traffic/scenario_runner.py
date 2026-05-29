"""
Phase 6 — Scenario Runner

Orchestrates 4 training phases over a Mininet network, launching and
tearing down traffic generators on host namespaces.

  Phase 1 (0–60s)   : Sensors only        — baseline, low BW
  Phase 2 (60–120s) : +Camera streams     — BW surge on S3/S4 uplinks
  Phase 3 (120–180s): +Elephant + Emergency — congestion + priority stress
  Phase 4 (180–240s): Recovery            — elephant gone, sensors + occasional video

Usage (called from iot_topology.py --train, or directly):
    sudo python3 traffic/scenario_runner.py          # spawns own Mininet
    from traffic.scenario_runner import ScenarioRunner
    runner = ScenarioRunner(net)
    runner.run()
"""

import os
import sys
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from constants import (
    IP_SENSOR1, IP_SENSOR2, IP_CAMERA1, IP_EMERG,
    IP_SENSOR3, IP_SENSOR4, IP_CAMERA2, IP_ACTUATOR,
    IP_SERVER1, IP_SERVER2,
    SENSOR_PORT, VIDEO_PORT, ELEPHANT_PORT, ACTUATOR_PORT,
)

GENERATOR = os.path.join(os.path.dirname(__file__), "generators.py")
PYTHON    = sys.executable


# ── Phase definition ──────────────────────────────────────────────────────────

@dataclass
class TrafficSpec:
    host_name: str          # Mininet host name, e.g. "h_sensor1"
    mode:      str          # generator mode
    dst_ip:    str          # destination IP
    extra:     list = field(default_factory=list)  # extra CLI flags


# Specs run in each phase (cumulative)
PHASE_SPECS = {
    # ── Phase 1: sensors baseline ─────────────────────────────────────────────
    1: [
        TrafficSpec("h_sensor1", "sensor",  IP_SERVER1, ["--duration", "240"]),
        TrafficSpec("h_sensor2", "sensor",  IP_SERVER1, ["--duration", "240"]),
        TrafficSpec("h_sensor3", "sensor",  IP_SERVER2, ["--duration", "240"]),
        TrafficSpec("h_sensor4", "sensor",  IP_SERVER2, ["--duration", "240"]),
    ],
    # ── Phase 2: camera streams ───────────────────────────────────────────────
    2: [
        TrafficSpec("h_camera1", "video",   IP_SERVER1,
                    ["--mbps", "5", "--duration", "180"]),
        TrafficSpec("h_camera2", "video",   IP_SERVER2,
                    ["--mbps", "5", "--duration", "180"]),
    ],
    # ── Phase 3: elephant flows + emergency ───────────────────────────────────
    3: [
        TrafficSpec("h_camera1",  "elephant", IP_SERVER1, ["--mb", "150"]),
        TrafficSpec("h_emerg",    "emergency", IP_SERVER1, ["--duration", "60"]),
        TrafficSpec("h_actuator", "actuator",  IP_SERVER2, ["--duration", "60"]),
    ],
    # ── Phase 4: recovery (light video only) ──────────────────────────────────
    4: [
        TrafficSpec("h_camera1", "video", IP_SERVER1,
                    ["--mbps", "2", "--duration", "60"]),
    ],
}

# Servers needed on h_server1 and h_server2
SERVER_SPECS = [
    (IP_SERVER1, "h_server1", "server-udp",  SENSOR_PORT),
    (IP_SERVER1, "h_server1", "server-udp",  VIDEO_PORT),
    (IP_SERVER1, "h_server1", "server-tcp",  ELEPHANT_PORT),
    (IP_SERVER1, "h_server1", "server-udp",  ACTUATOR_PORT),
    (IP_SERVER2, "h_server2", "server-udp",  SENSOR_PORT),
    (IP_SERVER2, "h_server2", "server-udp",  VIDEO_PORT),
    (IP_SERVER2, "h_server2", "server-tcp",  ELEPHANT_PORT),
    (IP_SERVER2, "h_server2", "server-udp",  ACTUATOR_PORT),
]


# ── Runner ────────────────────────────────────────────────────────────────────

class ScenarioRunner:
    """
    Launches traffic generators on Mininet hosts.

    Args:
        net        : running Mininet network object
        phase_secs : duration of each phase in seconds (default 60 each)
    """

    def __init__(self, net, phase_secs: int = 60):
        self.net        = net
        self.phase_secs = phase_secs
        self._procs: list[object] = []   # Popen-like objects (Mininet popens)

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self):
        print("\n=== Scenario Runner starting ===", flush=True)
        self._start_servers()
        print("[runner] Waiting 2s for servers to bind...", flush=True)
        time.sleep(2)

        try:
            for phase in sorted(PHASE_SPECS):
                self._start_phase(phase)
                self._wait_phase(phase)
        except KeyboardInterrupt:
            print("\n[runner] Interrupted — stopping all traffic", flush=True)
        finally:
            self.stop_all()
            print("=== Scenario Runner done ===\n", flush=True)

    def stop_all(self):
        for proc in self._procs:
            try:
                proc.send_signal(signal.SIGINT)
            except Exception:
                pass
        time.sleep(0.5)
        for proc in self._procs:
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
        self._procs.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _start_servers(self):
        seen = set()
        for _, host_name, mode, port in SERVER_SPECS:
            key = (host_name, port)
            if key in seen:
                continue
            seen.add(key)
            host = self.net.get(host_name)
            cmd  = [PYTHON, GENERATOR, mode, "--port", str(port)]
            proc = host.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self._procs.append(proc)
            print(f"[runner] server  {host_name} {mode} :{port}", flush=True)

    def _start_phase(self, phase: int):
        specs = PHASE_SPECS[phase]
        t = time.strftime("%H:%M:%S")
        print(f"\n[runner] [{t}] ── Phase {phase} start "
              f"({len(specs)} new flows) ──────", flush=True)
        for spec in specs:
            host = self.net.get(spec.host_name)
            cmd  = [PYTHON, GENERATOR, spec.mode, "--dst", spec.dst_ip] + spec.extra
            proc = host.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self._procs.append(proc)
            print(f"[runner]   {spec.host_name:12s} {spec.mode:10s} → {spec.dst_ip}", flush=True)

    def _wait_phase(self, phase: int):
        """Wait phase_secs then print a separator."""
        deadline = time.time() + self.phase_secs
        while time.time() < deadline:
            remaining = int(deadline - time.time())
            print(f"[runner] Phase {phase} — {remaining}s remaining", end="\r", flush=True)
            time.sleep(5)
        print()   # newline after \r


# ── Standalone entry point ────────────────────────────────────────────────────

def _standalone():
    """
    Boot Mininet topology and run the scenario.
    Must be run with sudo.
    """
    from mininet.log import setLogLevel
    setLogLevel("warning")

    # Import topology builder
    top_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, top_dir)
    from mininet.iot_topology import build_net

    net = build_net(use_remote_controller=True)
    net.start()
    print("[runner] Mininet started — waiting 2s for controller", flush=True)
    time.sleep(2)

    runner = ScenarioRunner(net, phase_secs=60)
    try:
        runner.run()
    finally:
        net.stop()


if __name__ == "__main__":
    _standalone()
