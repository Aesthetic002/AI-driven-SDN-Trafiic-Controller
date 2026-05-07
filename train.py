"""
Integration entry point — starts every component and runs the training scenario.

Must be run with sudo (Mininet needs root):
    sudo .venv/bin/python3 train.py [--phases N] [--phase-secs S] [--no-dashboard]

Start order:
    1. Ryu controller subprocess  (OpenFlow :6633)
    2. Flask API thread            (REST     :5000)
    3. Dashboard HTTP thread       (HTTP     :8080)
    4. Mininet topology            (OvS bridges)
    5. Traffic scenario runner     (4-phase traffic)
    6. Wait / monitor until done or Ctrl-C
    7. Save final weights, print summary
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from constants import (
    CONTROLLER_HOST, CONTROLLER_PORT,
    API_HOST, API_PORT, DASHBOARD_PORT,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _port_open(host, port, timeout=1.0) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _wait_for_port(host, port, label, retries=30, interval=1.0):
    print(f"[train] waiting for {label} ({host}:{port})...", end="", flush=True)
    for _ in range(retries):
        if _port_open(host, port):
            print(" ready", flush=True)
            return True
        print(".", end="", flush=True)
        time.sleep(interval)
    print(" TIMEOUT", flush=True)
    return False


# ── Component launchers ───────────────────────────────────────────────────────

_procs: list[subprocess.Popen] = []
_threads: list[threading.Thread] = []


def start_ryu() -> subprocess.Popen:
    python = sys.executable
    controller = os.path.join(ROOT, "controller", "ryu_controller.py")
    proc = subprocess.Popen(
        [python, "-m", "ryu.cmd.manager",
         "--ofp-tcp-listen-port", str(CONTROLLER_PORT), controller],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    _procs.append(proc)
    print(f"[train] Ryu controller started (pid={proc.pid})")
    return proc


def _stream_output(proc, prefix):
    for line in proc.stdout:
        decoded = line.decode(errors="replace").rstrip()
        if decoded:
            print(f"[{prefix}] {decoded}", flush=True)


def start_flask():
    import api.app as flask_app
    from api.app import _file_pump
    threading.Thread(target=_file_pump, daemon=True).start()
    t = threading.Thread(
        target=lambda: flask_app.app.run(
            host=API_HOST, port=API_PORT, use_reloader=False, threaded=True
        ),
        daemon=True,
        name="flask-api",
    )
    t.start()
    _threads.append(t)
    print(f"[train] Flask API started on http://{API_HOST}:{API_PORT}")


def start_dashboard():
    import http.server
    os.chdir(os.path.join(ROOT, "dashboard"))
    handler = http.server.SimpleHTTPRequestHandler

    class _QuietHandler(handler):
        def log_message(self, *a): pass   # suppress per-request logs

    srv = http.server.HTTPServer(("", DASHBOARD_PORT), _QuietHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True, name="dashboard")
    t.start()
    _threads.append(t)
    os.chdir(ROOT)
    print(f"[train] Dashboard started on http://localhost:{DASHBOARD_PORT}")


def start_mininet(phase_secs: int):
    """Starts Mininet topology + scenario runner in the current process."""
    from mininet.log import setLogLevel
    setLogLevel("warning")

    # iot_topology lives in the project's mininet/ folder, not the pip package
    sys.path.insert(0, os.path.join(ROOT, "mininet"))
    from iot_topology import build_net
    from traffic.scenario_runner import ScenarioRunner

    print("[train] Starting Mininet topology...")
    net = build_net(use_remote_controller=True)
    net.start()
    print("[train] Mininet up — waiting 2s for switch registration...")
    time.sleep(2)

    runner = ScenarioRunner(net, phase_secs=phase_secs)
    print("[train] Starting traffic scenario (4 phases)...")
    try:
        runner.run()
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop_all()
        net.stop()
        print("[train] Mininet stopped.")


# ── Cleanup ───────────────────────────────────────────────────────────────────

def cleanup(sig=None, frame=None):
    print("\n[train] Shutting down...")
    for proc in _procs:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    sys.exit(0)


signal.signal(signal.SIGINT,  cleanup)
signal.signal(signal.SIGTERM, cleanup)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AI-SDN training orchestrator")
    parser.add_argument("--phase-secs", type=int, default=60,
                        help="Duration of each traffic phase in seconds (default 60)")
    parser.add_argument("--no-dashboard", action="store_true",
                        help="Skip starting the dashboard server")
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("ERROR: train.py must be run with sudo — Mininet needs root.")
        print("  sudo .venv/bin/python3 train.py --phase-secs 10")
        sys.exit(1)

    print("=" * 60)
    print("  AI-SDN IoT Training Run")
    print(f"  4 phases × {args.phase_secs}s = {4 * args.phase_secs}s total")
    print("=" * 60)

    # 1. Ryu controller
    ryu_proc = start_ryu()
    threading.Thread(
        target=_stream_output, args=(ryu_proc, "ryu"), daemon=True
    ).start()

    if not _wait_for_port(CONTROLLER_HOST, CONTROLLER_PORT, "Ryu"):
        print("[train] ERROR: Ryu did not start. Check controller/ryu_controller.py")
        cleanup()
        return

    # 2. Flask API (reads Ryu's JSON file)
    start_flask()
    _wait_for_port(API_HOST, API_PORT, "Flask API", retries=10)

    # 3. Dashboard
    if not args.no_dashboard:
        start_dashboard()
        print(f"[train] Open dashboard → http://localhost:{DASHBOARD_PORT}")

    print()
    print("[train] All services up. Starting Mininet + traffic...")
    print("[train] Press Ctrl-C to stop early.")
    print()

    # 4+5. Mininet + traffic scenario (blocks until all 4 phases complete)
    t0 = time.time()
    try:
        start_mininet(args.phase_secs)
    except Exception as exc:
        print(f"[train] Mininet error: {exc}")

    elapsed = time.time() - t0

    # 6. Summary
    print()
    print("=" * 60)
    print(f"  Training complete in {elapsed:.0f}s")
    try:
        import json
        from constants import RUNTIME_STATE_FILE
        with open(RUNTIME_STATE_FILE) as f:
            snap = json.load(f)
        print(f"  Learn steps   : {snap['learn_steps']}")
        print(f"  Epsilon       : {snap['epsilon']:.4f}")
        print(f"  Total reward  : {snap['total_reward']:.2f}")
        print(f"  Last loss     : {snap.get('last_loss', 'N/A')}")
        print(f"  Path A flows  : {snap['path_counts'].get('PATH_A', 0)}")
        print(f"  Path B flows  : {snap['path_counts'].get('PATH_B', 0)}")
        print(f"  Path C flows  : {snap['path_counts'].get('PATH_C', 0)}")
        print(f"  Dropped flows : {snap['path_counts'].get('DROP', 0)}")
    except Exception:
        pass
    print("=" * 60)

    cleanup()


if __name__ == "__main__":
    main()
