"""
Traffic generators — run inside Mininet host namespaces via host.popen().

Each mode is a standalone process:
  server-udp  : listens on a UDP port and discards data (use on h_server1/2)
  server-tcp  : listens on a TCP port and discards data
  sensor      : periodic 100-byte UDP datagrams  (DSCP AF41, ~1 pkt/s)
  video       : continuous UDP stream            (DSCP AF31, ~5 Mbps)
  elephant    : TCP bulk transfer                (DSCP BE,   saturates link)
  emergency   : periodic urgent UDP              (DSCP EF,   10 pkt/s)
  actuator    : periodic control commands        (DSCP EF,   5 pkt/s)

Usage (called by scenario_runner via host.popen):
  python3 traffic/generators.py server-udp --port 5005
  python3 traffic/generators.py sensor     --dst 10.0.0.9 --duration 60
  python3 traffic/generators.py video      --dst 10.0.0.9 --duration 60 --mbps 5
  python3 traffic/generators.py elephant   --dst 10.0.0.9 --mb 200
  python3 traffic/generators.py emergency  --dst 10.0.0.9 --duration 60
  python3 traffic/generators.py actuator   --dst 10.0.0.9 --duration 60
"""

import argparse
import os
import socket
import struct
import sys
import time
import threading


# ── DSCP marking ──────────────────────────────────────────────────────────────

def _make_udp_socket(dscp: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tos  = dscp << 2          # DSCP occupies top 6 bits of TOS byte
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, tos)
    return sock


def _make_tcp_socket(dscp: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tos  = dscp << 2
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, tos)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return sock


# ── Server modes ──────────────────────────────────────────────────────────────

def run_server_udp(port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    total = 0
    print(f"[server-udp] listening on :{port}", flush=True)
    try:
        while True:
            data, _ = sock.recvfrom(65535)
            total += len(data)
    except KeyboardInterrupt:
        print(f"[server-udp] :{port} done — {total/1024:.1f} KB received", flush=True)
    finally:
        sock.close()


def run_server_tcp(port: int):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(16)
    print(f"[server-tcp] listening on :{port}", flush=True)

    def _handle(conn):
        total = 0
        try:
            while True:
                d = conn.recv(65536)
                if not d:
                    break
                total += len(d)
        finally:
            conn.close()
        print(f"[server-tcp] connection closed — {total/1024:.1f} KB", flush=True)

    try:
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=_handle, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()


# ── Client modes ──────────────────────────────────────────────────────────────

def run_sensor(dst: str, port: int, duration: float, dscp: int):
    """Periodic 100-byte UDP datagrams simulating an IoT sensor reading."""
    sock     = _make_udp_socket(dscp)
    deadline = time.time() + duration
    seq      = 0
    sent     = 0
    print(f"[sensor] → {dst}:{port} for {duration}s DSCP={dscp}", flush=True)
    try:
        while time.time() < deadline:
            payload = struct.pack("!IId", seq, int(time.time()), 23.5 + seq * 0.01)
            payload += b"\x00" * (100 - len(payload))   # pad to 100 bytes
            sock.sendto(payload, (dst, port))
            sent += 1
            seq  += 1
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    print(f"[sensor] done — {sent} packets sent", flush=True)


def run_video(dst: str, port: int, duration: float, mbps: float, dscp: int):
    """
    Continuous UDP stream at ~mbps Mbps simulating a camera feed.
    Uses 1400-byte payloads (near-MTU) to stress the link.
    """
    sock       = _make_udp_socket(dscp)
    pkt_size   = 1400                               # bytes
    target_bps = mbps * 1e6
    interval   = (pkt_size * 8) / target_bps       # seconds between packets
    deadline   = time.time() + duration
    seq        = 0
    sent_bytes = 0
    print(f"[video] → {dst}:{port} at {mbps} Mbps for {duration}s DSCP={dscp}", flush=True)
    try:
        next_send = time.time()
        while time.time() < deadline:
            payload = struct.pack("!II", seq, int(time.time() * 1000))
            payload += bytes([seq & 0xFF]) * (pkt_size - len(payload))
            sock.sendto(payload, (dst, port))
            sent_bytes += pkt_size
            seq        += 1
            next_send  += interval
            sleep_for   = next_send - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    print(f"[video] done — {sent_bytes/1e6:.2f} MB sent", flush=True)


def run_elephant(dst: str, port: int, mb: int, dscp: int):
    """TCP bulk transfer — sends `mb` megabytes as fast as possible."""
    chunk      = 65536                    # 64 KB write chunks
    total_goal = mb * 1024 * 1024        # bytes
    sent       = 0
    payload    = b"\xAB" * chunk
    print(f"[elephant] → {dst}:{port}  {mb} MB DSCP={dscp}", flush=True)
    try:
        sock = _make_tcp_socket(dscp)
        sock.connect((dst, port))
        t0 = time.time()
        while sent < total_goal:
            remaining = total_goal - sent
            n = sock.send(payload[:min(chunk, remaining)])
            if n == 0:
                break
            sent += n
        elapsed = time.time() - t0
        sock.close()
        print(f"[elephant] done — {sent/1e6:.2f} MB in {elapsed:.1f}s "
              f"({sent/elapsed/1e6:.2f} MB/s)", flush=True)
    except (ConnectionRefusedError, OSError) as e:
        print(f"[elephant] error: {e}", flush=True)


def run_emergency(dst: str, port: int, duration: float, dscp: int):
    """High-priority UDP bursts at 10 pkt/s simulating an emergency alert."""
    sock     = _make_udp_socket(dscp)
    deadline = time.time() + duration
    seq      = 0
    sent     = 0
    print(f"[emergency] → {dst}:{port} for {duration}s DSCP={dscp}", flush=True)
    try:
        while time.time() < deadline:
            payload = struct.pack("!II?", seq, int(time.time()), True)
            payload += b"EMERGENCY" + b"\x00" * (50 - len(payload))
            sock.sendto(payload, (dst, port))
            sent += 1
            seq  += 1
            time.sleep(0.1)   # 10 pkt/s
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    print(f"[emergency] done — {sent} packets sent", flush=True)


def run_actuator(dst: str, port: int, duration: float, dscp: int):
    """Control command UDP at 5 pkt/s simulating an actuator command stream."""
    sock     = _make_udp_socket(dscp)
    deadline = time.time() + duration
    seq      = 0
    sent     = 0
    print(f"[actuator] → {dst}:{port} for {duration}s DSCP={dscp}", flush=True)
    try:
        while time.time() < deadline:
            # Simulate a compact actuator command: seq + timestamp + setpoint
            payload = struct.pack("!IId", seq, int(time.time()), 75.0)
            sock.sendto(payload, (dst, port))
            sent += 1
            seq  += 1
            time.sleep(0.2)   # 5 pkt/s
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    print(f"[actuator] done — {sent} packets sent", flush=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="IoT traffic generator / server")
    p.add_argument("mode", choices=[
        "server-udp", "server-tcp",
        "sensor", "video", "elephant", "emergency", "actuator",
    ])
    p.add_argument("--dst",      default="10.0.0.9",  help="Destination IP")
    p.add_argument("--port",     type=int, default=0,  help="Override port")
    p.add_argument("--duration", type=float, default=60.0, help="Run seconds")
    p.add_argument("--mbps",     type=float, default=5.0,  help="Video Mbps")
    p.add_argument("--mb",       type=int,   default=100,  help="Elephant MB")
    p.add_argument("--dscp",     type=int,   default=-1,   help="Override DSCP")
    args = p.parse_args()

    # Default ports and DSCP per mode
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from constants import (
            SENSOR_PORT, VIDEO_PORT, ELEPHANT_PORT, ACTUATOR_PORT,
            DSCP_SENSOR, DSCP_VIDEO, DSCP_ELEPHANT, DSCP_EMERGENCY,
        )
    except ImportError:
        SENSOR_PORT = 5005; VIDEO_PORT = 5006
        ELEPHANT_PORT = 5007; ACTUATOR_PORT = 5008
        DSCP_SENSOR = 34; DSCP_VIDEO = 26; DSCP_ELEPHANT = 0; DSCP_EMERGENCY = 46

    defaults = {
        "server-udp": (SENSOR_PORT,   0),
        "server-tcp": (ELEPHANT_PORT, 0),
        "sensor":     (SENSOR_PORT,   DSCP_SENSOR),
        "video":      (VIDEO_PORT,    DSCP_VIDEO),
        "elephant":   (ELEPHANT_PORT, DSCP_ELEPHANT),
        "emergency":  (SENSOR_PORT,   DSCP_EMERGENCY),
        "actuator":   (ACTUATOR_PORT, DSCP_EMERGENCY),
    }
    def_port, def_dscp = defaults[args.mode]
    port = args.port if args.port else def_port
    dscp = args.dscp if args.dscp >= 0 else def_dscp

    if args.mode == "server-udp":
        run_server_udp(port)
    elif args.mode == "server-tcp":
        run_server_tcp(port)
    elif args.mode == "sensor":
        run_sensor(args.dst, port, args.duration, dscp)
    elif args.mode == "video":
        run_video(args.dst, port, args.duration, args.mbps, dscp)
    elif args.mode == "elephant":
        run_elephant(args.dst, port, args.mb, dscp)
    elif args.mode == "emergency":
        run_emergency(args.dst, port, args.duration, dscp)
    elif args.mode == "actuator":
        run_actuator(args.dst, port, args.duration, dscp)


if __name__ == "__main__":
    main()
