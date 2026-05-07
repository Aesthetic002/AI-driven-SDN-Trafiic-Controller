# AI-Driven SDN Controller for Intelligent IoT Traffic Steering
### Complete Step-by-Step Implementation Guide

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Deep Dive](#2-architecture-deep-dive)
3. [Environment Setup — Laptop (Edge Gateway)](#3-environment-setup--laptop-edge-gateway)
4. [Open vSwitch Configuration](#4-open-vswitch-configuration)
5. [Mininet Network Topology](#5-mininet-network-topology)
6. [SDN Controller Setup (Cloud VM)](#6-sdn-controller-setup-cloud-vm)
7. [IoT Traffic Generators](#7-iot-traffic-generators)
8. [Routing Policy Implementations](#8-routing-policy-implementations)
9. [Deep Q-Network (DQN) AI Agent](#9-deep-q-network-dqn-ai-agent)
10. [Controller ↔ AI Integration](#10-controller--ai-integration)
11. [Monitoring & Statistics Collection](#11-monitoring--statistics-collection)
12. [Visualization Dashboard](#12-visualization-dashboard)
13. [Experiment Design & Evaluation](#13-experiment-design--evaluation)
14. [Final Demo Walkthrough](#14-final-demo-walkthrough)
15. [Troubleshooting Reference](#15-troubleshooting-reference)

---

## 1. Project Overview

### What We're Building

This project builds a **Software Defined Network (SDN)** system where an AI agent dynamically routes IoT traffic based on real-time network conditions — replacing dumb static routing with an intelligent, adaptive controller.

### Why This Matters

| Traditional Routing | AI-SDN Routing |
|---|---|
| Fixed shortest-path (Dijkstra) | Dynamic path selection |
| No traffic awareness | Traffic-type aware |
| Bottlenecks under load | Congestion avoidance |
| No adaptability | Learns from experience |

### Three Core Policies We Compare

1. **Shortest Path** — classic Dijkstra, always picks minimum hops
2. **ECMP** — distributes flows round-robin across equal-cost paths
3. **DQN Routing** — AI picks path based on observed network state

---

## 2. Architecture Deep Dive

```
┌─────────────────────────────────────────────────────────────┐
│                        IoT Device Layer                     │
│  ESP32 Sensors ──── Android Camera ──── IoT Actuators       │
└───────────────────────────┬─────────────────────────────────┘
                            │ WiFi / Ethernet
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      Edge Gateway                           │
│  Manjaro Laptop                                             │
│  ├── Open vSwitch (programmable switch layer)               │
│  ├── Mininet (virtual network emulator)                     │
│  └── iperf3 / Python traffic generators                     │
└───────────────────────────┬─────────────────────────────────┘
                            │ OpenFlow Protocol (TCP:6633)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    SDN Control Plane (Cloud VM)             │
│  ├── Ryu Controller (OpenFlow manager)                      │
│  ├── DQN AI Agent (PyTorch)                                 │
│  └── REST API (Flask) — exposes routing decisions           │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP / WebSocket
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                        │
│  ├── Monitoring Dashboard (D3.js + Flask)                   │
│  ├── Traffic Visualizer                                     │
│  └── Experiment Manager                                     │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow for a Single Packet

```
IoT Device sends packet
        │
        ▼
Edge Switch (OvS) — is there a matching flow rule?
        │
   NO ──┘──► PacketIn event sent to Ryu Controller
                    │
                    ▼
              Ryu queries AI Agent via REST
                    │
                    ▼
              AI Agent returns: "use path 2"
                    │
                    ▼
              Ryu installs FlowMod rule in switch
                    │
                    ▼
        Subsequent packets forwarded by switch directly
```

---

## 3. Environment Setup — Laptop (Edge Gateway)

### 3.1 System Update

```bash
sudo pacman -Syu
```

> Always start fresh. A stale package index causes dependency errors with Mininet and OvS.

### 3.2 Install Core Network Tools

```bash
sudo pacman -S openvswitch mininet iperf3 wireshark-qt python python-pip git
```

**What each package does:**

| Package | Role |
|---|---|
| `openvswitch` | Programmable software switch (OpenFlow-enabled) |
| `mininet` | Virtual network topology emulator |
| `iperf3` | TCP/UDP bandwidth testing tool |
| `wireshark-qt` | Packet capture and inspection |
| `python` | Runtime for all scripts |

### 3.3 Install Python Dependencies

```bash
pip install requests flask flask-socketio scapy numpy
```

### 3.4 Verify Installations

```bash
# Check OvS
ovs-vsctl --version
# Expected: ovs-vsctl (Open vSwitch) 3.x.x

# Check Mininet
mn --version
# Expected: 2.3.x

# Check iperf3
iperf3 --version
# Expected: iperf 3.x.x
```

---

## 4. Open vSwitch Configuration

Open vSwitch (OvS) is the software switch that receives forwarding instructions from the Ryu controller via OpenFlow.

### 4.1 Start OvS Services

```bash
# Start the database server (stores OvS config persistently)
sudo systemctl start ovsdb-server
sudo systemctl enable ovsdb-server

# Start the switch daemon
sudo systemctl start ovs-vswitchd
sudo systemctl enable ovs-vswitchd
```

### 4.2 Create the Bridge (Virtual Switch)

```bash
# Create a bridge called sdn-br
sudo ovs-vsctl add-br sdn-br

# Set OpenFlow version to 1.3 (required for Ryu DQN integration)
sudo ovs-vsctl set bridge sdn-br protocols=OpenFlow13

# Verify
sudo ovs-vsctl show
```

**Expected output:**
```
Bridge sdn-br
    Port sdn-br
        Interface sdn-br
            type: internal
```

### 4.3 Connect OvS to the SDN Controller

```bash
# Replace <VM-IP> with your cloud VM's public IP
sudo ovs-vsctl set-controller sdn-br tcp:<VM-IP>:6633

# Verify connection state
sudo ovs-vsctl get-controller sdn-br
# Should show: tcp:<VM-IP>:6633
```

> **Important:** The switch will NOT forward any traffic until the controller is reachable. If the controller is offline, packets are dropped by default.

### 4.4 Add Physical Ports (for real IoT devices)

```bash
# Add your physical ethernet/wifi interface to the bridge
sudo ovs-vsctl add-port sdn-br eth0

# Verify
sudo ovs-ofctl show sdn-br
```

---

## 5. Mininet Network Topology

Mininet emulates an entire virtual network on one machine. We use it to test routing policies before deploying on real hardware.

### 5.1 Test Basic Topology

```bash
# Create a simple tree topology: 2 levels deep
sudo mn --topo tree,depth=2 --controller remote,ip=<VM-IP>,port=6633 --switch ovsk,protocols=OpenFlow13
```

### 5.2 Custom IoT Topology Script

Create file: `iot_topology.py`

```python
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.cli import CLI

class IoTTopology(Topo):
    """
    Topology:
    
        h_sensor1 ──┐
        h_sensor2 ──┤── s1 ──── s2 ──── h_server
        h_camera  ──┘    │
                         └── s3 ──── h_server2
    
    - h_sensor* = IoT sensor nodes (low bandwidth)
    - h_camera  = Video stream node (high bandwidth)
    - h_server  = Data collection server
    - s1, s2, s3 = OpenFlow switches
    """
    
    def build(self):
        # Create switches
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')
        
        # Create hosts (IoT devices)
        sensor1 = self.addHost('h_sensor1', ip='10.0.0.1/24')
        sensor2 = self.addHost('h_sensor2', ip='10.0.0.2/24')
        camera  = self.addHost('h_camera',  ip='10.0.0.3/24')
        server  = self.addHost('h_server',  ip='10.0.0.10/24')
        server2 = self.addHost('h_server2', ip='10.0.0.11/24')
        
        # IoT devices connect to s1
        self.addLink(sensor1, s1, bw=1,   delay='2ms')   # 1 Mbps, low delay sensor
        self.addLink(sensor2, s1, bw=1,   delay='2ms')
        self.addLink(camera,  s1, bw=10,  delay='5ms')   # 10 Mbps for video
        
        # Two paths from s1 to server (enables multipath/AI routing)
        self.addLink(s1, s2, bw=5,  delay='10ms')  # Path A (5 Mbps)
        self.addLink(s1, s3, bw=5,  delay='15ms')  # Path B (5 Mbps, higher delay)
        
        # Connect servers
        self.addLink(s2, server,  bw=100, delay='1ms')
        self.addLink(s3, server2, bw=100, delay='1ms')

def run():
    setLogLevel('info')
    topo = IoTTopology()
    net = Mininet(
        topo=topo,
        controller=RemoteController('c0', ip='<VM-IP>', port=6633),
        switch=OVSSwitch,
        link=TCLink,          # Enables bandwidth/delay constraints
        autoSetMacs=True
    )
    net.start()
    
    print("Network started. Type 'exit' to stop.")
    CLI(net)  # Opens interactive Mininet CLI
    
    net.stop()

if __name__ == '__main__':
    run()
```

```bash
# Run the topology
sudo python3 iot_topology.py
```

### 5.3 Test Connectivity

Inside the Mininet CLI:
```
mininet> pingall          # Test all-pairs connectivity
mininet> h_sensor1 ping h_server -c 3   # Specific ping
mininet> h_camera iperf -s &            # Start iperf server on camera
mininet> h_server iperf -c 10.0.0.3 -t 5  # Send traffic to camera
```

---

## 6. SDN Controller Setup (Cloud VM)

The cloud VM runs the Ryu controller and the AI routing agent.

### 6.1 VM Requirements

| Resource | Minimum |
|---|---|
| OS | Ubuntu 20.04 / 22.04 |
| RAM | 2 GB |
| CPU | 2 vCPUs |
| Ports | 6633 (OpenFlow), 8080 (REST API) |

### 6.2 Install Dependencies on VM

```bash
# System packages
sudo apt update && sudo apt install -y python3 python3-pip git curl

# Ryu SDN framework
pip3 install ryu

# AI/ML
pip3 install torch torchvision numpy

# API server
pip3 install flask flask-restx eventlet
```

### 6.3 Verify Ryu

```bash
ryu-manager --version
# Expected: ryu-manager 4.34

# Test with built-in simple switch app
ryu-manager ryu.app.simple_switch_13
# Should print: loading app ryu.app.simple_switch_13
```

### 6.4 Open Firewall Ports

```bash
# Allow OpenFlow traffic from the laptop
sudo ufw allow 6633/tcp    # OpenFlow
sudo ufw allow 8080/tcp    # REST API
sudo ufw allow 8888/tcp    # Dashboard WebSocket
sudo ufw reload
```

### 6.5 Project Directory Structure

```
sdn-iot/
├── controller/
│   ├── sdn_controller.py      # Main Ryu app
│   ├── routing_policies.py    # SP, ECMP, AI routing logic
│   └── topology_manager.py    # Graph of switches and links
├── ai_agent/
│   ├── dqn_agent.py           # Deep Q-Network
│   ├── environment.py         # State/reward definitions
│   └── model_weights.pth      # Saved model (after training)
├── api/
│   └── rest_api.py            # Flask REST API
├── traffic_generators/
│   ├── sensor_traffic.py      # ESP32-like periodic small packets
│   ├── video_traffic.py       # Continuous high-bandwidth stream
│   └── elephant_flow.py       # Large burst transfer
├── monitoring/
│   ├── stats_collector.py     # Poll OvS for statistics
│   └── logger.py
└── dashboard/
    ├── app.py                 # Flask + WebSocket server
    ├── templates/index.html
    └── static/
        ├── topology.js        # D3.js network graph
        └── charts.js          # Live metrics charts
```

---

## 7. IoT Traffic Generators

### 7.1 Sensor Traffic Generator

Simulates ESP32 sensors sending temperature/humidity data every 5 seconds.

File: `traffic_generators/sensor_traffic.py`

```python
import socket
import time
import json
import random
import argparse

def generate_sensor_data():
    """Simulate realistic IoT sensor readings."""
    return {
        "device_id": "esp32_001",
        "timestamp": time.time(),
        "temperature": round(random.uniform(22.0, 35.0), 2),
        "humidity":    round(random.uniform(40.0, 80.0), 2),
        "heart_rate":  random.randint(60, 100)
    }

def run_sensor(server_ip, server_port=5005, interval=5):
    """
    Send sensor data packets at fixed intervals.
    Packet size is intentionally tiny (~100 bytes).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    print(f"[Sensor] Sending to {server_ip}:{server_port} every {interval}s")
    
    while True:
        data = generate_sensor_data()
        payload = json.dumps(data).encode('utf-8')
        
        try:
            sock.sendto(payload, (server_ip, server_port))
            print(f"[Sensor] Sent {len(payload)} bytes: temp={data['temperature']}°C")
        except Exception as e:
            print(f"[Sensor] Error: {e}")
        
        time.sleep(interval)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', required=True, help='Server IP')
    parser.add_argument('--port',   type=int, default=5005)
    parser.add_argument('--interval', type=float, default=5.0)
    args = parser.parse_args()
    
    run_sensor(args.server, args.port, args.interval)
```

### 7.2 Video Traffic Generator

Simulates an Android camera sending a continuous 2–5 Mbps video stream.

File: `traffic_generators/video_traffic.py`

```python
import socket
import time
import os
import argparse

CHUNK_SIZE = 1400   # ~MTU-safe UDP packet size
TARGET_MBPS = 3     # 3 Mbps target bandwidth

def calculate_sleep(chunk_size, target_mbps):
    """Calculate inter-packet sleep to hit target bandwidth."""
    bits_per_chunk = chunk_size * 8
    bits_per_second = target_mbps * 1_000_000
    return bits_per_chunk / bits_per_second   # seconds between packets

def run_video_stream(server_ip, server_port=5006, duration=60):
    """
    Continuously send fake video frame chunks.
    Each chunk = 1400 bytes of random bytes (simulating compressed video).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sleep_interval = calculate_sleep(CHUNK_SIZE, TARGET_MBPS)
    
    start = time.time()
    total_bytes = 0
    
    print(f"[Video] Streaming to {server_ip}:{server_port} at ~{TARGET_MBPS} Mbps")
    
    while (time.time() - start) < duration:
        chunk = os.urandom(CHUNK_SIZE)  # Random bytes simulate video payload
        
        try:
            sock.sendto(chunk, (server_ip, server_port))
            total_bytes += len(chunk)
        except Exception as e:
            print(f"[Video] Error: {e}")
            break
        
        time.sleep(sleep_interval)
    
    elapsed = time.time() - start
    actual_mbps = (total_bytes * 8) / (elapsed * 1_000_000)
    print(f"[Video] Done. Sent {total_bytes/1e6:.2f} MB in {elapsed:.1f}s ({actual_mbps:.2f} Mbps)")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', required=True)
    parser.add_argument('--duration', type=int, default=60)
    args = parser.parse_args()
    
    run_video_stream(args.server, duration=args.duration)
```

### 7.3 Elephant Flow Generator

Injects a large bulk file transfer to congest a link and test AI routing reaction.

File: `traffic_generators/elephant_flow.py`

```python
import socket
import os
import time
import argparse

def run_elephant_flow(server_ip, server_port=5007, size_mb=500):
    """
    Send a large bulk transfer (elephant flow).
    This is designed to congest a link and force the AI to reroute other flows.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP for reliability
    sock.connect((server_ip, server_port))
    
    chunk_size = 65536  # 64KB chunks
    total_bytes = size_mb * 1024 * 1024
    sent = 0
    start = time.time()
    
    print(f"[Elephant] Sending {size_mb} MB to {server_ip}:{server_port}")
    
    while sent < total_bytes:
        chunk = os.urandom(min(chunk_size, total_bytes - sent))
        sock.sendall(chunk)
        sent += len(chunk)
        
        # Progress every 50MB
        if sent % (50 * 1024 * 1024) == 0:
            elapsed = time.time() - start
            speed_mbps = (sent * 8) / (elapsed * 1e6)
            print(f"[Elephant] {sent/1e6:.0f} MB sent ({speed_mbps:.1f} Mbps)")
    
    elapsed = time.time() - start
    print(f"[Elephant] Complete: {size_mb} MB in {elapsed:.1f}s")
    sock.close()
```

---

## 8. Routing Policy Implementations

File: `controller/routing_policies.py`

### 8.1 Shortest Path Routing

```python
import networkx as nx

class ShortestPathRouter:
    """
    Classic Dijkstra routing. Always uses minimum hop-count path.
    Problem: All flows share the same path → bottleneck under load.
    """
    
    def __init__(self, topology_graph):
        self.graph = topology_graph   # networkx DiGraph
    
    def get_path(self, src_dpid, dst_dpid, flow_info=None):
        """
        Returns the shortest path as a list of switch DPIDs.
        flow_info is ignored — this policy is traffic-blind.
        """
        try:
            path = nx.shortest_path(self.graph, src_dpid, dst_dpid, weight='hops')
            return path
        except nx.NetworkXNoPath:
            return None
```

### 8.2 ECMP Routing

```python
class ECMPRouter:
    """
    Equal Cost Multipath routing.
    Distributes flows round-robin across equal-cost paths.
    Improves load distribution but still doesn't react to congestion.
    """
    
    def __init__(self, topology_graph):
        self.graph = topology_graph
        self.flow_counter = 0  # Round-robin counter
    
    def get_all_shortest_paths(self, src_dpid, dst_dpid):
        """Get all paths with minimum hop count."""
        try:
            all_paths = list(nx.all_shortest_paths(self.graph, src_dpid, dst_dpid, weight='hops'))
            return all_paths
        except nx.NetworkXNoPath:
            return []
    
    def get_path(self, src_dpid, dst_dpid, flow_info=None):
        """Select a path using round-robin across equal-cost paths."""
        paths = self.get_all_shortest_paths(src_dpid, dst_dpid)
        
        if not paths:
            return None
        
        # Round-robin selection
        selected_index = self.flow_counter % len(paths)
        self.flow_counter += 1
        
        return paths[selected_index]
```

---

## 9. Deep Q-Network (DQN) AI Agent

### 9.1 Network State Definition

The AI observes a **state vector** at each decision point:

```
State = [link1_utilization, link2_utilization, link3_utilization,
         link1_queue_length, link2_queue_length, link3_queue_length,
         avg_packet_delay, flow_type_encoding]

State size: 8 features (normalized to [0, 1])
```

### 9.2 Action Space

```
Action 0: Route via Path A (s1 → s2 → server)
Action 1: Route via Path B (s1 → s3 → server2)
Action 2: Drop / Queue (for low-priority flows under extreme congestion)

Action space size: 3
```

### 9.3 Reward Function

```
reward = 1.0 / (flow_completion_time + ε)    if flow completes successfully
reward = -1.0                                 if flow times out or packet loss > threshold
```

Higher reward = shorter completion time = better routing decision.

### 9.4 DQN Implementation

File: `ai_agent/dqn_agent.py`

```python
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import random
from collections import deque

# --- Neural Network Architecture ---

class QNetwork(nn.Module):
    """
    Deep Q-Network: maps state → Q-values for each action.
    
    Input:  8-dimensional state vector
    Output: 3 Q-values (one per action/path)
    """
    
    def __init__(self, state_size=8, action_size=3, hidden_size=64):
        super(QNetwork, self).__init__()
        
        self.network = nn.Sequential(
            nn.Linear(state_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, action_size)
        )
    
    def forward(self, x):
        return self.network(x)


# --- Replay Memory ---

class ReplayBuffer:
    """
    Experience replay buffer.
    Stores (state, action, reward, next_state, done) transitions.
    Breaks temporal correlation in training data.
    """
    
    def __init__(self, capacity=10000):
        self.buffer = deque(maxlen=capacity)
    
    def push(self, state, action, reward, next_state, done):
        self.buffer.append((state, action, reward, next_state, done))
    
    def sample(self, batch_size):
        return random.sample(self.buffer, batch_size)
    
    def __len__(self):
        return len(self.buffer)


# --- DQN Agent ---

class DQNAgent:
    """
    Deep Q-Network agent for SDN path selection.
    
    Uses:
    - Double DQN (reduces overestimation bias)
    - Experience replay
    - ε-greedy exploration
    - Target network (stabilizes training)
    """
    
    def __init__(self, state_size=8, action_size=3):
        self.state_size  = state_size
        self.action_size = action_size
        
        # Hyperparameters
        self.gamma        = 0.95   # Discount factor: how much future rewards matter
        self.epsilon      = 1.0    # Exploration rate (starts at 100%)
        self.epsilon_min  = 0.01   # Minimum exploration (1%)
        self.epsilon_decay= 0.995  # Decay per step
        self.lr           = 0.001  # Learning rate
        self.batch_size   = 64
        
        # Networks
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.q_network      = QNetwork(state_size, action_size).to(self.device)
        self.target_network = QNetwork(state_size, action_size).to(self.device)
        self.target_network.load_state_dict(self.q_network.state_dict())
        
        self.optimizer = optim.Adam(self.q_network.parameters(), lr=self.lr)
        self.memory = ReplayBuffer(capacity=10000)
        self.steps  = 0
        self.target_update_freq = 100  # Sync target network every 100 steps
    
    def select_action(self, state):
        """
        ε-greedy action selection.
        - With probability ε: pick a RANDOM path (exploration)
        - With probability 1-ε: pick the BEST path per Q-values (exploitation)
        """
        if random.random() < self.epsilon:
            return random.randint(0, self.action_size - 1)
        
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        
        with torch.no_grad():
            q_values = self.q_network(state_tensor)
        
        return q_values.argmax().item()
    
    def remember(self, state, action, reward, next_state, done):
        """Store experience in replay buffer."""
        self.memory.push(state, action, reward, next_state, done)
    
    def train(self):
        """
        Sample a mini-batch and update the Q-network using the Bellman equation:
        
        Q(s, a) ← reward + γ * max_a' Q_target(s', a')
        """
        if len(self.memory) < self.batch_size:
            return None  # Not enough data yet
        
        batch = self.memory.sample(self.batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        
        # Convert to tensors
        states      = torch.FloatTensor(np.array(states)).to(self.device)
        actions     = torch.LongTensor(actions).to(self.device)
        rewards     = torch.FloatTensor(rewards).to(self.device)
        next_states = torch.FloatTensor(np.array(next_states)).to(self.device)
        dones       = torch.BoolTensor(dones).to(self.device)
        
        # Current Q-values
        current_q = self.q_network(states).gather(1, actions.unsqueeze(1)).squeeze(1)
        
        # Target Q-values (Bellman equation)
        with torch.no_grad():
            next_q    = self.target_network(next_states).max(1)[0]
            target_q  = rewards + self.gamma * next_q * (~dones)
        
        # Compute loss and backprop
        loss = nn.MSELoss()(current_q, target_q)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        # Decay exploration
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
        
        # Periodically sync target network
        self.steps += 1
        if self.steps % self.target_update_freq == 0:
            self.target_network.load_state_dict(self.q_network.state_dict())
        
        return loss.item()
    
    def save(self, path='model_weights.pth'):
        torch.save(self.q_network.state_dict(), path)
        print(f"[DQN] Model saved to {path}")
    
    def load(self, path='model_weights.pth'):
        self.q_network.load_state_dict(torch.load(path, map_location=self.device))
        self.target_network.load_state_dict(self.q_network.state_dict())
        self.epsilon = self.epsilon_min  # No exploration on loaded model
        print(f"[DQN] Model loaded from {path}")
```

### 9.5 Network Environment

File: `ai_agent/environment.py`

```python
import numpy as np
import time

class NetworkEnvironment:
    """
    Wraps the SDN network as a gym-like environment.
    State: normalized network metrics from OvS stats.
    Reward: derived from flow completion time and packet loss.
    """
    
    NUM_PATHS = 3
    STATE_SIZE = 8   # [3 link utils, 3 queue lengths, avg_delay, flow_type]
    
    def __init__(self, stats_collector):
        self.stats = stats_collector
        self.flow_start_times = {}   # flow_id → start timestamp
    
    def get_state(self):
        """
        Build the normalized state vector from current OvS statistics.
        All values normalized to [0, 1].
        """
        metrics = self.stats.get_latest()
        
        state = np.array([
            metrics.get('link1_util', 0.0)   / 100.0,  # 0–100% → 0–1
            metrics.get('link2_util', 0.0)   / 100.0,
            metrics.get('link3_util', 0.0)   / 100.0,
            metrics.get('link1_queue', 0)    / 1000.0,  # packets in queue
            metrics.get('link2_queue', 0)    / 1000.0,
            metrics.get('link3_queue', 0)    / 1000.0,
            metrics.get('avg_delay', 0.0)    / 100.0,  # ms, max ~100ms
            metrics.get('flow_type', 0)      / 3.0     # 0=sensor,1=video,2=elephant
        ], dtype=np.float32)
        
        return state
    
    def compute_reward(self, flow_id, flow_completion_time, packet_loss_rate):
        """
        Reward function:
        - High reward for fast, loss-free flows
        - Penalty for timeouts and packet loss
        """
        EPSILON = 1e-6   # Avoid division by zero
        
        if packet_loss_rate > 0.05:  # >5% packet loss
            return -1.0
        
        if flow_completion_time <= 0:
            return -1.0
        
        # Base reward inversely proportional to completion time
        reward = 1.0 / (flow_completion_time + EPSILON)
        
        # Bonus for zero packet loss
        if packet_loss_rate == 0:
            reward *= 1.2
        
        return min(reward, 10.0)   # Cap reward to avoid instability
```

---

## 10. Controller ↔ AI Integration

### 10.1 Main Ryu Controller App

File: `controller/sdn_controller.py`

```python
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, udp, tcp
from ryu.lib import hub
import requests
import json
import time

AI_AGENT_URL = "http://localhost:8080/api/routing"  # Flask REST API

class IoTSDNController(app_manager.RyuApp):
    """
    Main Ryu SDN controller.
    
    Responsibilities:
    1. Handle OpenFlow handshake with switches
    2. Detect new flows (PacketIn events)
    3. Query AI agent for routing decision
    4. Install FlowMod rules into switches
    5. Collect statistics periodically
    """
    
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    
    def __init__(self, *args, **kwargs):
        super(IoTSDNController, self).__init__(*args, **kwargs)
        
        self.mac_to_port   = {}    # {dpid: {mac: port}}
        self.topology      = {}    # {dpid: datapath object}
        self.active_flows  = {}    # {flow_id: path_info}
        self.routing_mode  = "ai"  # Options: "shortest", "ecmp", "ai"
        
        # Start background stats collection
        self.monitor_thread = hub.spawn(self._monitor_statistics)
        
        self.logger.info("IoT SDN Controller started. Mode: %s", self.routing_mode)
    
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """
        Called when a switch connects to the controller.
        Installs a table-miss flow entry: any unmatched packet → send to controller.
        """
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        
        self.topology[datapath.id] = datapath
        self.logger.info("Switch connected: dpid=%s", datapath.id)
        
        # Table-miss entry: match all packets, send to controller
        match  = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, priority=0, match=match, actions=actions)
    
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        Called when a switch receives an unmatched packet.
        We classify the traffic, query the AI, and install a flow rule.
        """
        msg      = ev.msg
        datapath = msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        in_port  = msg.match['in_port']
        
        # Parse packet
        pkt      = packet.Packet(msg.data)
        eth      = pkt.get_protocols(ethernet.ethernet)[0]
        ip_pkt   = pkt.get_protocol(ipv4.ipv4)
        
        if ip_pkt is None:
            return  # Ignore non-IP packets (ARP handled separately)
        
        # Classify flow type for AI state
        flow_type = self._classify_flow(pkt)
        
        # Get routing decision from AI agent
        if self.routing_mode == "ai":
            path = self._query_ai_agent(datapath.id, ip_pkt.dst, flow_type)
        elif self.routing_mode == "ecmp":
            path = self._ecmp_route(datapath.id, ip_pkt.dst)
        else:
            path = self._shortest_path_route(datapath.id, ip_pkt.dst)
        
        if path is None:
            self.logger.warning("No path found for dst=%s", ip_pkt.dst)
            return
        
        # Install flow rule for matched 5-tuple
        out_port = path[0]  # Next-hop port on this switch
        
        match = parser.OFPMatch(
            in_port=in_port,
            eth_type=0x0800,          # IPv4
            ipv4_src=ip_pkt.src,
            ipv4_dst=ip_pkt.dst
        )
        actions = [parser.OFPActionOutput(out_port)]
        
        # Install with idle_timeout so stale flows are removed
        self._add_flow(datapath, priority=10, match=match, actions=actions,
                       idle_timeout=30, hard_timeout=120)
        
        # Forward this packet immediately (before flow rule takes effect)
        self._send_packet(datapath, msg.buffer_id, in_port, out_port, msg.data)
    
    def _classify_flow(self, pkt):
        """
        Classify traffic type from packet headers.
        Returns: 0=sensor, 1=video, 2=elephant
        """
        udp_pkt = pkt.get_protocol(udp.udp)
        tcp_pkt = pkt.get_protocol(tcp.tcp)
        
        if udp_pkt:
            if udp_pkt.dst_port == 5005:
                return 0  # Sensor data (UDP, small)
            if udp_pkt.dst_port == 5006:
                return 1  # Video stream (UDP, large)
        
        if tcp_pkt and tcp_pkt.dst_port == 5007:
            return 2      # Elephant flow (TCP bulk transfer)
        
        return 0  # Default to sensor type
    
    def _query_ai_agent(self, dpid, dst_ip, flow_type):
        """
        Call the AI REST API to get the optimal routing path.
        Returns: port number to forward on.
        """
        try:
            payload = {
                "switch_id": dpid,
                "dst_ip":    dst_ip,
                "flow_type": flow_type
            }
            response = requests.post(AI_AGENT_URL, json=payload, timeout=0.1)
            data = response.json()
            return data.get("path")
        except Exception as e:
            self.logger.error("AI query failed: %s, falling back to shortest path", e)
            return self._shortest_path_route(dpid, dst_ip)
    
    def _add_flow(self, datapath, priority, match, actions,
                  idle_timeout=0, hard_timeout=0):
        """Install an OpenFlow flow rule into a switch."""
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)
    
    def _send_packet(self, datapath, buffer_id, in_port, out_port, data):
        """Send a packet out through a specific port."""
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        
        actions = [parser.OFPActionOutput(out_port)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=buffer_id,
            in_port=in_port,
            actions=actions,
            data=data
        )
        datapath.send_msg(out)
    
    def _monitor_statistics(self):
        """
        Background thread: polls switches for flow statistics every 5 seconds.
        Stats are used by the AI agent as the environment state.
        """
        while True:
            for dpid, datapath in self.topology.items():
                self._request_stats(datapath)
            hub.sleep(5)
    
    def _request_stats(self, datapath):
        """Send a FlowStatsRequest to get per-flow counters."""
        parser  = datapath.ofproto_parser
        ofproto = datapath.ofproto
        
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)
    
    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        """Receive and log flow statistics."""
        body = ev.msg.body
        
        for stat in sorted(body, key=lambda s: (s.match.get('ipv4_dst', '0'),)):
            self.logger.debug(
                "Flow: dst=%s packets=%d bytes=%d",
                stat.match.get('ipv4_dst', 'N/A'),
                stat.packet_count,
                stat.byte_count
            )
```

### 10.2 AI REST API

File: `api/rest_api.py`

```python
from flask import Flask, request, jsonify
import sys
sys.path.append('..')

from ai_agent.dqn_agent import DQNAgent
from ai_agent.environment import NetworkEnvironment

app = Flask(__name__)

# Initialize AI agent
agent = DQNAgent(state_size=8, action_size=3)

# Try loading pre-trained weights
try:
    agent.load('ai_agent/model_weights.pth')
    print("[API] Loaded pre-trained model.")
except FileNotFoundError:
    print("[API] No pre-trained model. Agent will train from scratch.")

# Path mapping: action index → (switch port, path description)
PATH_MAP = {
    0: {"port": 2, "description": "Path A: s1 → s2 → server"},
    1: {"port": 3, "description": "Path B: s1 → s3 → server2"},
    2: {"port": 2, "description": "Path A (fallback)"}
}

@app.route('/api/routing', methods=['POST'])
def get_routing_decision():
    """
    Input JSON:
    {
        "switch_id": 1,
        "dst_ip": "10.0.0.10",
        "flow_type": 1
    }
    
    Output JSON:
    {
        "action": 0,
        "path": 2,
        "description": "Path A: s1 → s2 → server",
        "epsilon": 0.45
    }
    """
    data = request.get_json()
    
    # Get current network state
    state = environment.get_state()
    
    # Override flow_type in state
    state[7] = data.get('flow_type', 0) / 3.0
    
    # AI selects action
    action = agent.select_action(state)
    path_info = PATH_MAP.get(action, PATH_MAP[0])
    
    return jsonify({
        "action":      action,
        "path":        path_info["port"],
        "description": path_info["description"],
        "epsilon":     round(agent.epsilon, 4)
    })

@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    """
    After a flow completes, the controller submits feedback for training.
    
    Input JSON:
    {
        "state": [...],
        "action": 0,
        "reward": 0.85,
        "next_state": [...],
        "done": true
    }
    """
    data = request.get_json()
    
    agent.remember(
        data['state'],
        data['action'],
        data['reward'],
        data['next_state'],
        data['done']
    )
    
    loss = agent.train()
    
    return jsonify({
        "status": "ok",
        "loss": loss,
        "epsilon": agent.epsilon
    })

@app.route('/api/save', methods=['POST'])
def save_model():
    agent.save('ai_agent/model_weights.pth')
    return jsonify({"status": "saved"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
```

### 10.3 Running the Full Stack

**On Cloud VM — Terminal 1: AI REST API**
```bash
cd sdn-iot
python3 api/rest_api.py
# Listening on 0.0.0.0:8080
```

**On Cloud VM — Terminal 2: Ryu Controller**
```bash
cd sdn-iot
ryu-manager controller/sdn_controller.py --observe-links --verbose
# Listening for switches on port 6633
```

**On Laptop — Terminal 1: Mininet**
```bash
sudo python3 iot_topology.py
# Virtual network starts, switches connect to cloud VM
```

---

## 11. Monitoring & Statistics Collection

File: `monitoring/stats_collector.py`

```python
import subprocess
import re
import time
import json
from threading import Thread, Lock

class OvSStatsCollector:
    """
    Polls Open vSwitch for real-time statistics using ovs-ofctl.
    Runs in a background thread and maintains a current snapshot.
    """
    
    def __init__(self, bridge='sdn-br', interval=2):
        self.bridge   = bridge
        self.interval = interval
        self.stats    = {}
        self.lock     = Lock()
        self._running = False
    
    def start(self):
        self._running = True
        Thread(target=self._collect_loop, daemon=True).start()
    
    def stop(self):
        self._running = False
    
    def get_latest(self):
        with self.lock:
            return dict(self.stats)
    
    def _collect_loop(self):
        while self._running:
            try:
                new_stats = self._poll_ovs()
                with self.lock:
                    self.stats = new_stats
            except Exception as e:
                print(f"[Stats] Collection error: {e}")
            time.sleep(self.interval)
    
    def _poll_ovs(self):
        """
        Run ovs-ofctl dump-ports to get per-port statistics.
        Returns dict with utilization, packet counts, errors.
        """
        result = subprocess.run(
            ['sudo', 'ovs-ofctl', 'dump-ports', self.bridge],
            capture_output=True, text=True
        )
        
        stats = {}
        current_port = None
        
        for line in result.stdout.split('\n'):
            # Match port number
            port_match = re.match(r'\s*port\s+(\d+):', line)
            if port_match:
                current_port = int(port_match.group(1))
                stats[f'port{current_port}'] = {}
            
            # Match RX packets
            rx_match = re.search(r'rx pkts=(\d+), bytes=(\d+)', line)
            if rx_match and current_port:
                stats[f'port{current_port}']['rx_pkts']  = int(rx_match.group(1))
                stats[f'port{current_port}']['rx_bytes'] = int(rx_match.group(2))
            
            # Match TX packets  
            tx_match = re.search(r'tx pkts=(\d+), bytes=(\d+)', line)
            if tx_match and current_port:
                stats[f'port{current_port}']['tx_pkts']  = int(tx_match.group(1))
                stats[f'port{current_port}']['tx_bytes'] = int(tx_match.group(2))
        
        # Compute utilization (bytes delta over interval)
        stats['timestamp'] = time.time()
        return stats
```

---

## 12. Visualization Dashboard

File: `dashboard/app.py`

```python
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from monitoring.stats_collector import OvSStatsCollector
import json, time, threading

app    = Flask(__name__)
socket = SocketIO(app, cors_allowed_origins="*")
stats  = OvSStatsCollector()

@app.route('/')
def index():
    return render_template('index.html')

@socket.on('connect')
def handle_connect():
    """Push live stats to dashboard every 2 seconds."""
    def push_stats():
        while True:
            data = stats.get_latest()
            socket.emit('stats_update', data)
            time.sleep(2)
    
    threading.Thread(target=push_stats, daemon=True).start()

if __name__ == '__main__':
    stats.start()
    socket.run(app, host='0.0.0.0', port=8888, debug=False)
```

File: `dashboard/templates/index.html`

```html
<!DOCTYPE html>
<html>
<head>
    <title>IoT SDN Monitor</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script src="https://cdn.socket.io/4.6.0/socket.io.min.js"></script>
    <style>
        body { font-family: monospace; background: #1a1a2e; color: #eee; margin: 0; padding: 20px; }
        .panel { background: #16213e; border: 1px solid #0f3460; border-radius: 8px; padding: 16px; margin: 10px; }
        h2 { color: #e94560; }
        .metric { display: inline-block; margin: 8px; padding: 12px; background: #0f3460; border-radius: 6px; }
        .metric-value { font-size: 2em; color: #e94560; }
        .metric-label { font-size: 0.8em; color: #aaa; }
        #topology svg { width: 100%; height: 300px; }
    </style>
</head>
<body>
    <h1>🔴 IoT SDN Live Dashboard</h1>

    <div class="panel">
        <h2>Network Metrics</h2>
        <div id="metrics"></div>
    </div>

    <div class="panel">
        <h2>Network Topology</h2>
        <div id="topology"></div>
    </div>

    <script>
        const socket = io();

        socket.on('stats_update', (data) => {
            // Update metrics panel
            const metricsDiv = document.getElementById('metrics');
            metricsDiv.innerHTML = '';

            for (const [key, val] of Object.entries(data)) {
                if (key === 'timestamp') continue;
                const div = document.createElement('div');
                div.className = 'metric';
                div.innerHTML = `
                    <div class="metric-value">${JSON.stringify(val)}</div>
                    <div class="metric-label">${key}</div>
                `;
                metricsDiv.appendChild(div);
            }
        });
    </script>
</body>
</html>
```

---

## 13. Experiment Design & Evaluation

### 13.1 Experiment Script

File: `run_experiment.py`

```python
"""
Runs three routing policies across three traffic scenarios.
Logs flow completion time, throughput, latency, and packet loss.
"""
import subprocess
import time
import json
import csv
import requests

CONTROLLER_URL = "http://<VM-IP>:8080"

def set_routing_mode(mode):
    """Switch the controller routing policy."""
    requests.post(f"{CONTROLLER_URL}/api/mode", json={"mode": mode})
    print(f"[Experiment] Routing mode set to: {mode}")
    time.sleep(2)  # Allow flow rules to flush

def run_traffic_scenario(scenario_name, duration=30):
    """Launch traffic generators for a given scenario."""
    procs = []
    
    if scenario_name == "uniform":
        # All sensors, no big flows
        for i in range(3):
            p = subprocess.Popen(
                ["python3", "traffic_generators/sensor_traffic.py",
                 "--server", "10.0.0.10", "--interval", "1"]
            )
            procs.append(p)
    
    elif scenario_name == "elephant":
        # Mix: sensors + one huge elephant flow
        p1 = subprocess.Popen(
            ["python3", "traffic_generators/sensor_traffic.py", "--server", "10.0.0.10"]
        )
        p2 = subprocess.Popen(
            ["python3", "traffic_generators/elephant_flow.py", "--server", "10.0.0.10"]
        )
        procs = [p1, p2]
    
    elif scenario_name == "adversarial":
        # Video + sensors + elephant (maximum congestion test)
        p1 = subprocess.Popen(
            ["python3", "traffic_generators/video_traffic.py", "--server", "10.0.0.10",
             "--duration", str(duration)]
        )
        p2 = subprocess.Popen(
            ["python3", "traffic_generators/sensor_traffic.py", "--server", "10.0.0.10"]
        )
        p3 = subprocess.Popen(
            ["python3", "traffic_generators/elephant_flow.py", "--server", "10.0.0.10"]
        )
        procs = [p1, p2, p3]
    
    time.sleep(duration)
    
    for p in procs:
        p.terminate()

def collect_metrics():
    """Query controller for flow statistics."""
    resp = requests.get(f"{CONTROLLER_URL}/api/stats")
    return resp.json()

# Run full experiment matrix
POLICIES   = ["shortest", "ecmp", "ai"]
SCENARIOS  = ["uniform", "elephant", "adversarial"]
results    = []

for policy in POLICIES:
    set_routing_mode(policy)
    
    for scenario in SCENARIOS:
        print(f"\n[Experiment] Policy={policy} | Scenario={scenario}")
        
        run_traffic_scenario(scenario, duration=60)
        metrics = collect_metrics()
        
        results.append({
            "policy":               policy,
            "scenario":             scenario,
            "avg_flow_completion":  metrics.get("avg_completion_time"),
            "throughput_mbps":      metrics.get("throughput_mbps"),
            "packet_loss_pct":      metrics.get("packet_loss_pct"),
            "avg_latency_ms":       metrics.get("avg_latency_ms")
        })
        
        print(f"  Result: {results[-1]}")
        time.sleep(5)  # Cooldown between experiments

# Save results
with open("experiment_results.csv", "w", newline='') as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

print("\n[Experiment] Complete. Results saved to experiment_results.csv")
```

### 13.2 Expected Results Table

| Policy | Uniform Traffic | Elephant Flow | Adversarial |
|---|---|---|---|
| Shortest Path | Low latency | **High congestion** | **Severe bottleneck** |
| ECMP | Low latency | Moderate | Moderate |
| AI (DQN) | Low latency | **Best** | **Best** |

### 13.3 Key Metrics to Plot

```python
# After experiment, generate comparison plots
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("experiment_results.csv")

fig, axes = plt.subplots(1, 3, figsize=(15, 5))
metrics = ['avg_flow_completion', 'throughput_mbps', 'packet_loss_pct']
titles  = ['Avg Flow Completion Time (s)', 'Throughput (Mbps)', 'Packet Loss (%)']

for ax, metric, title in zip(axes, metrics, titles):
    df.pivot(index='scenario', columns='policy', values=metric).plot(
        kind='bar', ax=ax, rot=0
    )
    ax.set_title(title)
    ax.set_xlabel('Scenario')
    ax.legend(['AI', 'ECMP', 'Shortest'])

plt.tight_layout()
plt.savefig("results_comparison.png", dpi=150)
plt.show()
```

---

## 14. Final Demo Walkthrough

### Demo Sequence

```bash
# === Terminal 1 (Cloud VM): Start AI API ===
python3 api/rest_api.py

# === Terminal 2 (Cloud VM): Start Ryu Controller ===
ryu-manager controller/sdn_controller.py --observe-links

# === Terminal 3 (Cloud VM): Start Dashboard ===
python3 dashboard/app.py

# === Terminal 4 (Laptop): Start Mininet ===
sudo python3 iot_topology.py

# === Terminal 5 (Laptop): Start Sensor Traffic ===
python3 traffic_generators/sensor_traffic.py --server 10.0.0.10

# === Terminal 6 (Laptop): Start Video Stream ===
python3 traffic_generators/video_traffic.py --server 10.0.0.10 --duration 120

# === Watch Dashboard ===
# Open http://<VM-IP>:8888 in browser

# === Terminal 7: Inject Elephant Flow (congestion trigger) ===
python3 traffic_generators/elephant_flow.py --server 10.0.0.10
# Observe: AI agent shifts sensor/video traffic to alternate path
```

### What to Show

| Event | Expected AI Behavior |
|---|---|
| Sensors only | All flows on Path A (optimal) |
| Video starts | AI keeps video on Path A, sensors stay low-priority |
| Elephant injected | AI detects congestion on Path A, shifts flows to Path B |
| Elephant ends | AI gradually migrates flows back to Path A |

---

## 15. Troubleshooting Reference

| Problem | Cause | Fix |
|---|---|---|
| Switch not connecting to controller | Firewall blocking port 6633 | `sudo ufw allow 6633/tcp` on VM |
| `ovs-vsctl: database connection failed` | ovsdb-server not running | `sudo systemctl start ovsdb-server` |
| Mininet: `RTNETLINK answers: File exists` | Previous Mininet session didn't clean up | `sudo mn -c` |
| AI API returns 500 | PyTorch not installed or model path wrong | `pip3 install torch` and verify path |
| No traffic between Mininet hosts | Table-miss flow not installed | Check controller is reachable; verify OpenFlow version is 1.3 |
| `ryu-manager: command not found` | Ryu not in PATH | Add `~/.local/bin` to PATH or use `python3 -m ryu.cmd.manager` |
| Flows not being learned | AI epsilon too high (all random) | Load pre-trained weights or run training for 1000+ episodes first |

### Quick Health Check Commands

```bash
# Check OvS bridge status
sudo ovs-vsctl show

# Check active flow rules on switch
sudo ovs-ofctl dump-flows sdn-br

# Check controller connection
sudo ovs-vsctl get-controller sdn-br

# Test Ryu REST API
curl http://<VM-IP>:8080/api/stats

# Monitor real-time OvS traffic
watch -n 1 'sudo ovs-ofctl dump-ports sdn-br'
```

---

*Guide Version 1.0 — AI-Driven SDN IoT Project*
