"""
Phase 1 — Virtual IoT Network Topology (3-cluster, 7-switch)

Architecture:
  ACCESS LAYER
    S1 (Cluster A): h_sensor1, h_sensor2, h_camera1, h_emerg
    S2 (Cluster B): h_sensor3, h_sensor4, h_camera2, h_actuator
    S6 (Cluster C): h_sensor5, h_sensor6, h_camera3, h_gateway  [NEW]

  CORE LAYER (dual-path + cross-link)
    S3  — low-latency path  (→ S5 primary, → S7 secondary)
    S4  — high-BW path      (→ S5 primary, → S7 secondary)
    S3 ↔ S4  cross-link (50 Mbps, 3ms — Path C overflow)

  AGGREGATION / SERVER LAYER
    S5: h_server1, h_server2  (primary,   50/100 Mbps from S3/S4)
    S7: h_server3, h_server4  (secondary,  75/80 Mbps from S3/S4)  [NEW]

  Routing paths (decided by DQN, 6 actions):
    Path A  S1/S2/S6 → S3 → S5   low latency   (7ms,  50Mbps)
    Path B  S1/S2/S6 → S4 → S5   high BW       (13ms, 100Mbps)
    Path C  S1/S2/S6 → S3↔S4→S5  cross-link overflow
    Path D  S1/S2/S6 → S3 → S7   secondary low-lat (10ms, 75Mbps)  [NEW]
    Path E  S1/S2/S6 → S4 → S7   secondary high-BW (15ms, 80Mbps)  [NEW]
    Drop    discard under extreme congestion

Run:
    sudo python3 mininet/iot_topology.py          # keep alive (needs Ryu)
    sudo python3 mininet/iot_topology.py --test   # pingall then exit
    sudo python3 mininet/iot_topology.py --cli    # interactive CLI
"""

import os
import sys
import argparse
import socket
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController, OVSController
from mininet.link import TCLink
from mininet.topo import Topo
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.util import dumpNodeConnections

try:
    from constants import (
        CONTROLLER_HOST, CONTROLLER_PORT,
        # Host IPs
        IP_SENSOR1, IP_SENSOR2, IP_CAMERA1, IP_EMERG,
        IP_SENSOR3, IP_SENSOR4, IP_CAMERA2, IP_ACTUATOR,
        IP_SERVER1, IP_SERVER2,
        IP_SENSOR5, IP_SENSOR6, IP_CAMERA3, IP_GATEWAY,
        IP_SERVER3, IP_SERVER4,
        # Bandwidths
        LINK_BW_SENSOR, LINK_BW_CAMERA, LINK_BW_ACTUATOR, LINK_BW_EMERGENCY,
        LINK_BW_ACCESS_CORE,
        LINK_BW_CORE_SERVER_A, LINK_BW_CORE_SERVER_B,
        LINK_BW_CORE_SERVER_C, LINK_BW_CORE_SERVER_D,
        LINK_BW_CROSSLINK, LINK_BW_SERVER,
        # Delays
        LINK_DELAY_SENSOR, LINK_DELAY_CAMERA,
        LINK_DELAY_ACTUATOR, LINK_DELAY_EMERGENCY,
        LINK_DELAY_S1_S3, LINK_DELAY_S1_S4,
        LINK_DELAY_S2_S3, LINK_DELAY_S2_S4,
        LINK_DELAY_S6_S3, LINK_DELAY_S6_S4,
        LINK_DELAY_S3_S5, LINK_DELAY_S4_S5,
        LINK_DELAY_S3_S7, LINK_DELAY_S4_S7,
        LINK_DELAY_CROSSLINK, LINK_DELAY_SERVER,
    )
except ImportError:
    # Fallback defaults so the file can be tested standalone
    CONTROLLER_HOST = "127.0.0.1"; CONTROLLER_PORT = 6633
    IP_SENSOR1 = "10.0.0.1";  IP_SENSOR2 = "10.0.0.2"
    IP_CAMERA1 = "10.0.0.3";  IP_EMERG = "10.0.0.4"
    IP_SENSOR3 = "10.0.0.5";  IP_SENSOR4 = "10.0.0.6"
    IP_CAMERA2 = "10.0.0.7";  IP_ACTUATOR = "10.0.0.8"
    IP_SERVER1 = "10.0.0.9";  IP_SERVER2 = "10.0.0.10"
    IP_SENSOR5 = "10.0.0.11"; IP_SENSOR6 = "10.0.0.12"
    IP_CAMERA3 = "10.0.0.13"; IP_GATEWAY = "10.0.0.14"
    IP_SERVER3 = "10.0.0.15"; IP_SERVER4 = "10.0.0.16"
    LINK_BW_SENSOR = 1;  LINK_BW_CAMERA = 10
    LINK_BW_ACTUATOR = 2; LINK_BW_EMERGENCY = 2
    LINK_BW_ACCESS_CORE = 20
    LINK_BW_CORE_SERVER_A = 50;  LINK_BW_CORE_SERVER_B = 100
    LINK_BW_CORE_SERVER_C = 75;  LINK_BW_CORE_SERVER_D = 80
    LINK_BW_CROSSLINK = 50;  LINK_BW_SERVER = 1000
    LINK_DELAY_SENSOR = "2ms";  LINK_DELAY_CAMERA = "5ms"
    LINK_DELAY_ACTUATOR = "1ms"; LINK_DELAY_EMERGENCY = "1ms"
    LINK_DELAY_S1_S3 = "5ms";  LINK_DELAY_S1_S4 = "8ms"
    LINK_DELAY_S2_S3 = "6ms";  LINK_DELAY_S2_S4 = "7ms"
    LINK_DELAY_S6_S3 = "5ms";  LINK_DELAY_S6_S4 = "8ms"
    LINK_DELAY_S3_S5 = "2ms";  LINK_DELAY_S4_S5 = "5ms"
    LINK_DELAY_S3_S7 = "4ms";  LINK_DELAY_S4_S7 = "6ms"
    LINK_DELAY_CROSSLINK = "3ms"; LINK_DELAY_SERVER = "1ms"


class IoTTopo(Topo):
    """
    3-cluster, 7-switch IoT topology.

    Port assignment (Mininet assigns in addLink order):

    S1: 1=sensor1  2=sensor2  3=camera1  4=emerg     5=→s3  6=→s4
    S2: 1=sensor3  2=sensor4  3=camera2  4=actuator  5=→s3  6=→s4
    S6: 1=sensor5  2=sensor6  3=camera3  4=gateway   5=→s3  6=→s4
    S3: 1=←s1  2=←s2  3=→s5  4=↔s4  5=←s6  6=→s7
    S4: 1=←s1  2=←s2  3=→s5  4=↔s3  5=←s6  6=→s7
    S5: 1=←s3  2=←s4  3=server1  4=server2
    S7: 1=←s3  2=←s4  3=server3  4=server4
    """

    def build(self, fail_mode="secure", stp=False):
        sw_opts = dict(cls=OVSSwitch, failMode=fail_mode, stp=stp)

        # ── Access switches ───────────────────────────────────────────────────
        s1 = self.addSwitch("s1", **sw_opts)
        s2 = self.addSwitch("s2", **sw_opts)
        s6 = self.addSwitch("s6", **sw_opts)   # Cluster C

        # ── Core switches ─────────────────────────────────────────────────────
        s3 = self.addSwitch("s3", **sw_opts)
        s4 = self.addSwitch("s4", **sw_opts)

        # ── Aggregation / server switches ─────────────────────────────────────
        s5 = self.addSwitch("s5", **sw_opts)
        s7 = self.addSwitch("s7", **sw_opts)   # Secondary aggregation

        # ── Cluster A hosts ───────────────────────────────────────────────────
        h_sensor1  = self.addHost("h_sensor1",  ip=IP_SENSOR1)
        h_sensor2  = self.addHost("h_sensor2",  ip=IP_SENSOR2)
        h_camera1  = self.addHost("h_camera1",  ip=IP_CAMERA1)
        h_emerg    = self.addHost("h_emerg",    ip=IP_EMERG)

        # ── Cluster B hosts ───────────────────────────────────────────────────
        h_sensor3  = self.addHost("h_sensor3",  ip=IP_SENSOR3)
        h_sensor4  = self.addHost("h_sensor4",  ip=IP_SENSOR4)
        h_camera2  = self.addHost("h_camera2",  ip=IP_CAMERA2)
        h_actuator = self.addHost("h_actuator", ip=IP_ACTUATOR)

        # ── Cluster C hosts ───────────────────────────────────────────────────
        h_sensor5  = self.addHost("h_sensor5",  ip=IP_SENSOR5)
        h_sensor6  = self.addHost("h_sensor6",  ip=IP_SENSOR6)
        h_camera3  = self.addHost("h_camera3",  ip=IP_CAMERA3)
        h_gateway  = self.addHost("h_gateway",  ip=IP_GATEWAY)

        # ── Server hosts (primary S5) ─────────────────────────────────────────
        h_server1  = self.addHost("h_server1",  ip=IP_SERVER1)
        h_server2  = self.addHost("h_server2",  ip=IP_SERVER2)

        # ── Server hosts (secondary S7) ───────────────────────────────────────
        h_server3  = self.addHost("h_server3",  ip=IP_SERVER3)
        h_server4  = self.addHost("h_server4",  ip=IP_SERVER4)

        # ── S1 — Cluster A access links (S1 ports 1-4) ───────────────────────
        self.addLink(h_sensor1,  s1, bw=LINK_BW_SENSOR,    delay=LINK_DELAY_SENSOR,
                     loss=0, max_queue_size=100)
        self.addLink(h_sensor2,  s1, bw=LINK_BW_SENSOR,    delay=LINK_DELAY_SENSOR,
                     loss=0, max_queue_size=100)
        self.addLink(h_camera1,  s1, bw=LINK_BW_CAMERA,    delay=LINK_DELAY_CAMERA,
                     loss=0, max_queue_size=500)
        self.addLink(h_emerg,    s1, bw=LINK_BW_EMERGENCY,  delay=LINK_DELAY_EMERGENCY,
                     loss=0, max_queue_size=50)

        # ── S2 — Cluster B access links (S2 ports 1-4) ───────────────────────
        self.addLink(h_sensor3,  s2, bw=LINK_BW_SENSOR,    delay=LINK_DELAY_SENSOR,
                     loss=0, max_queue_size=100)
        self.addLink(h_sensor4,  s2, bw=LINK_BW_SENSOR,    delay=LINK_DELAY_SENSOR,
                     loss=0, max_queue_size=100)
        self.addLink(h_camera2,  s2, bw=LINK_BW_CAMERA,    delay=LINK_DELAY_CAMERA,
                     loss=0, max_queue_size=500)
        self.addLink(h_actuator, s2, bw=LINK_BW_ACTUATOR,  delay=LINK_DELAY_ACTUATOR,
                     loss=0, max_queue_size=50)

        # ── S1 → core uplinks (S1 ports 5-6, S3 port 1, S4 port 1) ──────────
        self.addLink(s1, s3, bw=LINK_BW_ACCESS_CORE, delay=LINK_DELAY_S1_S3,
                     loss=0, max_queue_size=2000)
        self.addLink(s1, s4, bw=LINK_BW_ACCESS_CORE, delay=LINK_DELAY_S1_S4,
                     loss=0, max_queue_size=2000)

        # ── S2 → core uplinks (S2 ports 5-6, S3 port 2, S4 port 2) ──────────
        self.addLink(s2, s3, bw=LINK_BW_ACCESS_CORE, delay=LINK_DELAY_S2_S3,
                     loss=0, max_queue_size=2000)
        self.addLink(s2, s4, bw=LINK_BW_ACCESS_CORE, delay=LINK_DELAY_S2_S4,
                     loss=0, max_queue_size=2000)

        # ── Core → S5 primary aggregation (S3 port 3, S4 port 3, S5 ports 1-2)
        self.addLink(s3, s5, bw=LINK_BW_CORE_SERVER_A, delay=LINK_DELAY_S3_S5,
                     loss=0, max_queue_size=5000)
        self.addLink(s4, s5, bw=LINK_BW_CORE_SERVER_B, delay=LINK_DELAY_S4_S5,
                     loss=0, max_queue_size=5000)

        # ── S3 ↔ S4 cross-link (S3 port 4, S4 port 4) ───────────────────────
        self.addLink(s3, s4, bw=LINK_BW_CROSSLINK, delay=LINK_DELAY_CROSSLINK,
                     loss=0, max_queue_size=3000)

        # ── S5 — primary server access links (S5 ports 3-4) ──────────────────
        self.addLink(s5, h_server1, bw=LINK_BW_SERVER, delay=LINK_DELAY_SERVER,
                     loss=0, max_queue_size=10000)
        self.addLink(s5, h_server2, bw=LINK_BW_SERVER, delay=LINK_DELAY_SERVER,
                     loss=0, max_queue_size=10000)

        # ── S6 — Cluster C access links (S6 ports 1-4) ───────────────────────
        self.addLink(h_sensor5, s6, bw=LINK_BW_SENSOR,    delay=LINK_DELAY_SENSOR,
                     loss=0, max_queue_size=100)
        self.addLink(h_sensor6, s6, bw=LINK_BW_SENSOR,    delay=LINK_DELAY_SENSOR,
                     loss=0, max_queue_size=100)
        self.addLink(h_camera3, s6, bw=LINK_BW_CAMERA,    delay=LINK_DELAY_CAMERA,
                     loss=0, max_queue_size=500)
        self.addLink(h_gateway, s6, bw=LINK_BW_ACTUATOR,  delay=LINK_DELAY_ACTUATOR,
                     loss=0, max_queue_size=50)

        # ── S6 → core uplinks (S6 ports 5-6, S3 port 5, S4 port 5) ──────────
        self.addLink(s6, s3, bw=LINK_BW_ACCESS_CORE, delay=LINK_DELAY_S6_S3,
                     loss=0, max_queue_size=2000)
        self.addLink(s6, s4, bw=LINK_BW_ACCESS_CORE, delay=LINK_DELAY_S6_S4,
                     loss=0, max_queue_size=2000)

        # ── Core → S7 secondary aggregation (S3 port 6, S4 port 6, S7 ports 1-2)
        self.addLink(s3, s7, bw=LINK_BW_CORE_SERVER_C, delay=LINK_DELAY_S3_S7,
                     loss=0, max_queue_size=5000)
        self.addLink(s4, s7, bw=LINK_BW_CORE_SERVER_D, delay=LINK_DELAY_S4_S7,
                     loss=0, max_queue_size=5000)

        # ── S7 — secondary server access links (S7 ports 3-4) ────────────────
        self.addLink(s7, h_server3, bw=LINK_BW_SERVER, delay=LINK_DELAY_SERVER,
                     loss=0, max_queue_size=10000)
        self.addLink(s7, h_server4, bw=LINK_BW_SERVER, delay=LINK_DELAY_SERVER,
                     loss=0, max_queue_size=10000)


def build_net(use_remote_controller: bool = True) -> Mininet:
    if use_remote_controller:
        fail_mode = "secure"
        stp = False
        controller = lambda name: RemoteController(
            name, ip=CONTROLLER_HOST, port=CONTROLLER_PORT
        )
    else:
        # standalone = OVS built-in learning switch; STP needed for cross-link loop
        fail_mode = "standalone"
        stp = True
        controller = OVSController

    topo = IoTTopo(fail_mode=fail_mode, stp=stp)

    net = Mininet(
        topo=topo,
        controller=controller,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=True,
    )
    return net


def _ryu_reachable() -> bool:
    try:
        s = socket.create_connection((CONTROLLER_HOST, CONTROLLER_PORT), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def run(args):
    setLogLevel("info")

    ryu_up = _ryu_reachable()
    if not ryu_up:
        info(f"*** Ryu not reachable at {CONTROLLER_HOST}:{CONTROLLER_PORT}"
             " — falling back to OVSController (learning switch mode)\n")

    net = build_net(use_remote_controller=ryu_up)
    net.start()

    info("*** Topology ready. Node connections:\n")
    dumpNodeConnections(net.hosts)

    if args.test:
        if not ryu_up:
            info("*** Waiting 35s for STP convergence (standalone mode)...\n")
            time.sleep(35)
        info("*** Running pingall...\n")
        loss = net.pingAll()
        info(f"*** Packet loss: {loss:.1f}%\n")
        net.stop()
        sys.exit(0 if loss == 0.0 else 1)

    if args.cli:
        CLI(net)
    else:
        info("*** Network running. Ctrl-C to stop.\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    net.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="2-tier IoT SDN topology")
    parser.add_argument("--test", action="store_true", help="pingall then exit")
    parser.add_argument("--cli",  action="store_true", help="Mininet CLI")
    run(parser.parse_args())
