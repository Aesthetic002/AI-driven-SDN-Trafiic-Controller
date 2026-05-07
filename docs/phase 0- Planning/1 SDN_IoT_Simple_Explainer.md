# AI-Driven SDN for IoT — Explained Simply
### What we're building, why we're building it, and how it all works

---

## Table of Contents

1. [The Problem — Why Normal Networks Fail for IoT](#1-the-problem--why-normal-networks-fail-for-iot)
2. [The Big Idea — What is SDN?](#2-the-big-idea--what-is-sdn)
3. [Where AI Comes In](#3-where-ai-comes-in)
4. [The Full System — All Pieces Together](#4-the-full-system--all-pieces-together)
5. [The Hardware — What Physical Things We Use](#5-the-hardware--what-physical-things-we-use)
6. [The Software Stack — What Programs Run Where](#6-the-software-stack--what-programs-run-where)
7. [The Network Topology — How Devices Are Connected](#7-the-network-topology--how-devices-are-connected)
8. [Traffic Types — What Kind of Data Flows](#8-traffic-types--what-kind-of-data-flows)
9. [The Three Routing Policies — Old vs New](#9-the-three-routing-policies--old-vs-new)
10. [How the AI Learns — Deep Q-Network Explained](#10-how-the-ai-learns--deep-q-network-explained)
11. [How a Packet Travels Through the System](#11-how-a-packet-travels-through-the-system)
12. [The OpenFlow Protocol — How Controller Talks to Switch](#12-the-openflow-protocol--how-controller-talks-to-switch)
13. [Training the AI — The Learning Loop](#13-training-the-ai--the-learning-loop)
14. [The Monitoring Dashboard](#14-the-monitoring-dashboard)
15. [The Experiments — How We Prove It Works](#15-the-experiments--how-we-prove-it-works)
16. [The Final Demo — What the Audience Sees](#16-the-final-demo--what-the-audience-sees)
17. [How Everything Connects — The Big Picture](#17-how-everything-connects--the-big-picture)

---

## 1. The Problem — Why Normal Networks Fail for IoT

Imagine a hospital. It has hundreds of devices on the same network:

- A tiny temperature sensor that sends one small message every 5 seconds
- A security camera streaming HD video 24/7
- A device downloading a large firmware update in the background
- An emergency alert system that must reach the server **instantly**

All of these devices share the same network roads — the cables and routers.

**Traditional routers are dumb.** They only know one thing: *what is the shortest path to the destination?* They send everything down the same road. They don't care what the data is, how urgent it is, or how busy the road already is.

```mermaid
graph LR
    Sensor["🌡️ Sensor\n(tiny packets)"] --> Router
    Camera["📷 Camera\n(huge stream)"] --> Router
    Firmware["💾 Firmware\n(burst download)"] --> Router
    Alert["🚨 Emergency Alert\n(must be instant)"] --> Router

    Router -->|"SAME ROAD\nfor everything"| Server["🖥️ Server"]

    style Router fill:#c0392b,color:#fff
    style Alert fill:#e74c3c,color:#fff
```

**What goes wrong:**

| Situation                | What Happens                  | Consequence                |
| ------------------------ | ----------------------------- | -------------------------- |
| Camera starts streaming  | Road gets 80% congested       | Everything slows down      |
| Firmware download starts | Road is completely jammed     | Emergency alert is delayed |
| Two cameras at once      | Packets start getting dropped | Sensor data is lost        |

The router keeps sending everything through the same bottleneck path. It has no idea the emergency alert is critical. It has no idea the firmware update can wait. This is the core problem.

---

## 2. The Big Idea — What is SDN?

**SDN stands for Software Defined Networking.**

The key insight is: *separate the brain from the body.*

In a normal network, every switch/router has its own brain. Each one independently decides where to send packets. They can't coordinate. They can't adapt together.

In SDN, all the switches become "mindless forwarders." They just follow rules. One single **central controller** — the brain — tells all switches what to do.

```mermaid
graph TB
    subgraph "Traditional Network — Every switch thinks for itself"
        S1["Switch 1\n🧠 brain inside"] 
        S2["Switch 2\n🧠 brain inside"]
        S3["Switch 3\n🧠 brain inside"]
        S1 <--> S2
        S2 <--> S3
    end

    subgraph "SDN — One brain controls all switches"
        Controller["🧠 Central\nSDN Controller"]
        T1["Switch A\n(just follows rules)"]
        T2["Switch B\n(just follows rules)"]
        T3["Switch C\n(just follows rules)"]
        Controller -->|"rules"| T1
        Controller -->|"rules"| T2
        Controller -->|"rules"| T3
    end
```

**Why is this powerful?**

Because now the central controller can:
- See the **entire network** at once
- Know how busy every link is
- Install different rules for different types of traffic
- Change routing decisions in real time
- Be upgraded with new logic — like AI — without touching any switch

The switches themselves are just dumb boxes running **Open vSwitch** — a software switch that accepts instructions via the **OpenFlow protocol** (think of it like a remote control language).

---

## 3. Where AI Comes In

The SDN controller is the brain. But what should the brain's strategy be?

Even with full network visibility, deciding the optimal path for every flow — considering traffic type, link congestion, queue lengths, and delay — is too complex to hardcode with rules.

This is where **Reinforcement Learning AI** comes in.

Think of it like training a dog:
- The dog (AI) takes an action (chooses a path)
- It gets a treat (reward) if the flow completed fast with no packet loss
- It gets scolded (negative reward) if the flow was slow or dropped packets
- Over thousands of repetitions, the dog learns which actions lead to treats

Our AI model is called a **Deep Q-Network (DQN)**. It watches the network, picks a path, and learns from the result — getting smarter over time.

```mermaid
graph LR
    Network["🌐 Network\n(link congestion,\nqueue sizes,\npacket delay)"] -->|"state"| AI["🤖 AI Agent\n(Deep Q-Network)"]
    AI -->|"action:\nchoose path 1, 2, or 3"| Switch["🔀 Switch"]
    Switch -->|"flow result:\nfast? slow? dropped?"| Reward["🏆 Reward\nCalculation"]
    Reward -->|"train AI"| AI

    style AI fill:#2ecc71,color:#000
    style Reward fill:#f39c12,color:#000
```

---

## 4. The Full System — All Pieces Together

Here is every component of the project and how they connect:

```mermaid
graph TB
    subgraph IoT["📱 IoT Device Layer"]
        ESP32["ESP32\nTemperature Sensor"]
        Phone["Android Phone\nCamera Stream"]
        Other["Other IoT\nDevices"]
    end

    subgraph Edge["💻 Edge Gateway — Your Old Laptop"]
        OvS["Open vSwitch\n(programmable switch)"]
        Mininet["Mininet\n(virtual network\nfor testing)"]
        Generators["Traffic Generators\n(Python scripts\nsimulating IoT devices)"]
    end

    subgraph Cloud["☁️ Cloud VM — The Brain"]
        Ryu["Ryu Controller\n(SDN manager)"]
        DQN["DQN AI Agent\n(PyTorch)"]
        API["REST API\n(Flask — connects\nRyu ↔ AI)"]
    end

    subgraph Dashboard["📊 Monitoring"]
        UI["Web Dashboard\n(D3.js + WebSocket)"]
        Stats["Stats Collector\n(OvS metrics)"]
    end

    ESP32 -->|"WiFi"| OvS
    Phone -->|"WiFi"| OvS
    Generators --> Mininet
    Mininet --> OvS

    OvS <-->|"OpenFlow\nTCP:6633"| Ryu
    Ryu <-->|"HTTP"| API
    API <-->|"state/action"| DQN

    OvS -->|"port stats"| Stats
    Stats --> UI
    Ryu -->|"flow events"| UI

    style Cloud fill:#1a1a2e,color:#fff
    style Edge fill:#16213e,color:#fff
    style IoT fill:#0f3460,color:#fff
    style Dashboard fill:#1b1b2f,color:#fff
```

---

## 5. The Hardware — What Physical Things We Use

We need surprisingly little hardware. Here's what each piece does:

```mermaid
graph LR
    subgraph HW["Physical Hardware"]
        Laptop["🖥️ Old Laptop\nManjaro Linux\n\n• Acts as the network switch\n• Runs Open vSwitch\n• Runs Mininet emulator\n• Generates test traffic"]

        ESP32["📟 ESP32\nMicrocontroller\n\n• Sends real temperature\n  and humidity data\n• Connects via WiFi\n• Very low power"]

        Phone["📱 Android Phone\n\n• Streams video traffic\n• Simulates a smart camera\n• Creates high bandwidth load"]

        VM["☁️ Cloud VM\n(any provider)\n\n• Runs the Ryu controller\n• Runs the AI agent\n• Accessible from laptop\n  via internet"]
    end
```

**Why use Mininet on the laptop instead of real switches?**

Real network switches cost thousands of dollars. Mininet lets you simulate an entire network — multiple switches, hosts, links with specific speeds and delays — all on one laptop. For testing and research, this is perfect. You can test 10 different topologies in an afternoon.

---

## 6. The Software Stack — What Programs Run Where

```mermaid
graph TB
    subgraph Laptop["💻 Laptop"]
        direction TB
        OvS2["Open vSwitch\nThe actual software switch.\nForwards packets based on\nrules from the controller."]
        MN["Mininet\nCreates a fake network of\nvirtual switches and hosts\nfor testing without\nreal hardware."]
        iperf["iperf3\nGenerates test traffic.\nLike a hose that pours\ndata through the network\nso we can measure performance."]
        Wire["Wireshark\nCaptures and shows\nevery packet.\nOur microscope for\nthe network."]
    end

    subgraph VM["☁️ Cloud VM"]
        direction TB
        RyuApp["Ryu Controller\nPython app that manages\nOpenFlow switches.\nReceives events, makes\nrouting decisions."]
        PT["PyTorch\nDeep learning library.\nPowers the DQN neural\nnetwork that learns\noptimal routing."]
        Flask["Flask REST API\nBridge between Ryu\nand the AI agent.\nRyu asks: 'what path?'\nFlask asks AI, returns answer."]
    end
```

---

## 7. The Network Topology — How Devices Are Connected

We build this virtual network inside Mininet:

```mermaid
graph TB
    Sensor1["🌡️ h_sensor1\n10.0.0.1"] -->|"1 Mbps, 2ms"| S1
    Sensor2["🌡️ h_sensor2\n10.0.0.2"] -->|"1 Mbps, 2ms"| S1
    Camera["📷 h_camera\n10.0.0.3"] -->|"10 Mbps, 5ms"| S1

    S1["Switch S1\n(main hub)"]

    S1 -->|"PATH A\n5 Mbps, 10ms"| S2["Switch S2"]
    S1 -->|"PATH B\n5 Mbps, 15ms"| S3["Switch S3"]

    S2 -->|"100 Mbps, 1ms"| Server1["🖥️ h_server\n10.0.0.10"]
    S3 -->|"100 Mbps, 1ms"| Server2["🖥️ h_server2\n10.0.0.11"]

    style S1 fill:#e74c3c,color:#fff
    style S2 fill:#3498db,color:#fff
    style S3 fill:#3498db,color:#fff
    style Server1 fill:#27ae60,color:#fff
    style Server2 fill:#27ae60,color:#fff
```

**Key design choices:**

- **Two paths from S1 to servers** — This gives the AI a choice. Without two paths, there's nothing to optimize.
- **Path A vs Path B** — Both have 5 Mbps bandwidth, but Path B has 5ms more delay. AI learns when to use each.
- **Different link speeds for IoT devices** — Sensors get 1 Mbps (realistic for ESP32 WiFi), camera gets 10 Mbps (realistic for video).
- **Fast server connections** — 100 Mbps, because servers shouldn't be the bottleneck in our experiment.

---

## 8. Traffic Types — What Kind of Data Flows

We simulate three very different types of IoT traffic. Each one stresses the network differently.

```mermaid
graph TB
    subgraph ST["🌡️ Sensor Traffic"]
        S_desc["Small packets — ~100 bytes each\nSent every 5 seconds\nContains: temperature, humidity, heart rate\nLike: WhatsApp texts — tiny but time sensitive\nBandwidth needed: almost zero\nLatency requirement: moderate"]
    end

    subgraph VT["📷 Video Traffic"]
        V_desc["Large continuous stream\n1400-byte chunks sent constantly\nTarget: 2–5 Mbps sustained\nLike: YouTube live stream\nBandwidth needed: HIGH\nLatency requirement: moderate (buffered)"]
    end

    subgraph ET["🐘 Elephant Flow"]
        E_desc["One massive bulk transfer\nExample: 500 MB firmware update\nFills up the entire link\nLike: copying a Blu-ray over WiFi\nBandwidth needed: ALL of it\nLatency requirement: don't care — just finish"]
    end
```

**Why these three matter:**

The elephant flow is the villain. When it starts, it tries to consume the entire 5 Mbps path. A dumb router keeps sending the sensor and video traffic down the same congested road. Our AI controller should detect this and shift the sensor/video to Path B — keeping their performance intact while the elephant uses Path A.

---

## 9. The Three Routing Policies — Old vs New

We implement and compare three different strategies for deciding which path to use.

### Policy 1: Shortest Path Routing

```mermaid
graph LR
    subgraph "Shortest Path — Always takes fewest hops"
        SP1["Sensor"] -->|"→ Path A"| SP_S1["S1"]
        SP2["Camera"] -->|"→ Path A"| SP_S1
        SP3["Elephant"] -->|"→ Path A"| SP_S1
        SP_S1 -->|"ALL TRAFFIC\njammed here"| SP_S2["S2"] --> SP_SRV["Server"]
        SP_S1 -.->|"Path B\nnever used"| SP_S3["S3"] -.-> SP_SRV2["Server2"]
    end
    style SP_S1 fill:#c0392b,color:#fff
    style SP_S2 fill:#c0392b,color:#fff
```

Everything goes the same way. Path B sits empty. Path A becomes a traffic jam. Simple to implement, poor performance under load.

---

### Policy 2: ECMP (Equal Cost Multipath)

```mermaid
graph LR
    subgraph "ECMP — Takes turns on equal paths"
        E1["Flow 1 (Sensor)"] -->|"→ Path A"| E_S1["S1"]
        E2["Flow 2 (Camera)"] -->|"→ Path B"| E_S1
        E3["Flow 3 (Elephant)"] -->|"→ Path A"| E_S1
        E4["Flow 4 (Sensor)"] -->|"→ Path B"| E_S1
        E_S1 -->|"Path A\n~half traffic"| E_S2["S2"] --> E_SRV["Server"]
        E_S1 -->|"Path B\n~half traffic"| E_S3["S3"] --> E_SRV2["Server2"]
    end
```

Better than Shortest Path — at least both paths are used. But it's still blind. It might put the huge Elephant Flow and a critical sensor on the same path just because it's "that flow's turn."

---

### Policy 3: AI (DQN) Routing

```mermaid
graph TB
    subgraph "AI Routing — Thinks before deciding"
        State["Observes network state:\n- Path A utilization: 90% 🔴\n- Path B utilization: 20% 🟢\n- Sensor flow detected\n- Elephant flow on Path A"]

        Decision["AI decides:\nSensor → Path B 🟢\n(Path A is congested)\nElephant stays on Path A\n(it got there first)"]

        Result["Result:\nSensor gets low latency ✅\nCamera gets low latency ✅\nElephant finishes without\ndisturbing others ✅"]

        State --> Decision --> Result
    end
    style State fill:#2c3e50,color:#fff
    style Decision fill:#27ae60,color:#fff
    style Result fill:#2980b9,color:#fff
```

The AI doesn't follow a fixed rule. It looks at what's actually happening right now and picks the best path for each flow type. This is the key advantage.

---

## 10. How the AI Learns — Deep Q-Network Explained

Don't be scared by "Deep Q-Network." Here's what it actually means, step by step.

### What is Q-Learning?

Q stands for "Quality." We want to know: *"How good is this action in this situation?"*

We build a table:

| Situation (State) | Take Path A | Take Path B |
|---|---|---|
| Path A: 10% busy, Path B: 10% busy | Q = 8.5 | Q = 8.2 |
| Path A: 90% busy, Path B: 20% busy | Q = 1.2 | Q = 9.1 |
| Path A: 50% busy, Path B: 50% busy | Q = 5.0 | Q = 4.9 |

The AI always picks the action with the **highest Q value** in the current situation.

### Why "Deep"?

The state of our network has 8 numbers (link utilizations, queue lengths, delay, flow type). There are infinite possible combinations. We can't store a table big enough.

So instead of a table, we use a **neural network** to estimate Q values. That's the "Deep" part — a neural network is layers of math that can approximate any function.

```mermaid
graph LR
    subgraph "Neural Network (QNetwork)"
        Input["Input Layer\n8 numbers:\nlink1_util\nlink2_util\nlink3_util\nlink1_queue\nlink2_queue\nlink3_queue\navg_delay\nflow_type"]

        H1["Hidden Layer 1\n64 neurons\n(ReLU activation)"]
        H2["Hidden Layer 2\n64 neurons\n(ReLU activation)"]

        Output["Output Layer\n3 numbers:\nQ(Path A)\nQ(Path B)\nQ(Drop/Queue)"]

        Input --> H1 --> H2 --> Output
    end

    Output -->|"Pick highest Q"| Decision["✅ Chosen Action"]
```

### The Learning Loop

```mermaid
sequenceDiagram
    participant Net as 🌐 Network
    participant Agent as 🤖 AI Agent
    participant Memory as 🧠 Replay Buffer
    participant Train as 📉 Training

    Net->>Agent: Current state (8 numbers)
    Agent->>Agent: Pick action (ε-greedy)
    Note over Agent: 80% of time: pick best known action<br/>20% of time: pick random action (explore!)
    Agent->>Net: Install routing rule
    Net->>Agent: Reward (based on flow completion time)
    Agent->>Memory: Store (state, action, reward, next_state)
    Memory->>Train: Random batch of 64 past experiences
    Train->>Agent: Update network weights
    Note over Train: Bellman equation:<br/>Q(s,a) = reward + 0.95 × max Q(next_state)
```

**Why store past experiences and train randomly?**

If we trained on every experience in order, the AI would only remember the most recent situation. By storing thousands of past experiences and sampling randomly, it learns from a diverse mix — like studying flashcards rather than just reading the last chapter.

### Exploration vs Exploitation (ε-greedy)

This is a fundamental challenge: should the AI try new things or stick to what it knows works?

```mermaid
graph LR
    subgraph "Early Training (ε = 1.0 = 100% random)"
        E_early["Agent tries random paths\nLearns what happens\nBuilds up knowledge\n'Like a tourist exploring\na new city'"]
    end

    subgraph "Mid Training (ε = 0.5 = 50/50)"
        E_mid["Half the time: use best known path\nHalf the time: try something new\n'Like a local who still\ntries new restaurants'"]
    end

    subgraph "Late Training (ε = 0.01 = 1% random)"
        E_late["99% of time: use best known path\n1% of time: explore\n'Like an expert who\nknows the best routes'"]
    end

    E_early -->|"epsilon decays\nover time"| E_mid --> E_late
```

---

## 11. How a Packet Travels Through the System

Let's follow a single emergency sensor reading from an ESP32 to the server.

```mermaid
sequenceDiagram
    participant ESP as 📟 ESP32 Sensor
    participant OvS as 🔀 Open vSwitch
    participant Ryu as 🧠 Ryu Controller
    participant AI as 🤖 AI Agent
    participant Srv as 🖥️ Server

    ESP->>OvS: "Temperature = 32°C" (UDP packet)

    OvS->>OvS: Check flow table — any matching rule?
    Note over OvS: No rule found for this flow!

    OvS->>Ryu: PacketIn event (sends packet to controller)

    Ryu->>Ryu: Parse packet — what is it?
    Note over Ryu: UDP, dst_port=5005 → Sensor traffic, type=0

    Ryu->>AI: POST /api/routing<br/>{"switch_id": 1, "dst_ip": "10.0.0.10", "flow_type": 0}

    AI->>AI: Read current network state
    Note over AI: Path A: 85% busy (elephant flow!)<br/>Path B: 15% busy → use Path B

    AI->>Ryu: {"path": 3, "description": "Path B: S1→S3→Server2"}

    Ryu->>OvS: FlowMod: "For all sensor packets → forward to port 3"
    Note over OvS: Rule installed. All future sensor packets<br/>will go directly to Path B without asking controller.

    OvS->>Srv: Packet forwarded via Path B ✅

    Note over OvS,Ryu: Next sensor packet arrives —<br/>OvS finds the rule instantly,<br/>no need to ask controller again
```

**The key insight:** The controller is only consulted for the **first packet** of each flow. After that, the switch handles it directly using the installed rule. This makes it fast — no controller bottleneck for every packet.

---

## 12. The OpenFlow Protocol — How Controller Talks to Switch

OpenFlow is the language the controller uses to program switches. Think of it like a waiter taking orders from the chef (controller) and delivering them to the kitchen (switch).

```mermaid
graph TB
    subgraph "OpenFlow Message Types"
        FM["📋 FlowMod\n'Add this rule to your table:\nIf packet from 10.0.0.3 → Port 5005,\nsend it out port 3'"]

        PI["📦 PacketIn\n'Hey controller, I got a packet\nand I don't know what to do with it.\nHere it is — what should I do?'"]

        PO["📤 PacketOut\n'Take this packet and send it\nout of port 2 right now'"]

        SR["📊 StatsRequest/Reply\n'Controller: give me your\ncurrent packet counts'\nSwitch: 'port1: 5000 pkts,\nport2: 12000 pkts...'"]
    end

    Controller["🧠 Ryu Controller"] -->|"FlowMod"| Switch["🔀 OvS Switch"]
    Switch -->|"PacketIn"| Controller
    Controller -->|"PacketOut"| Switch
    Controller -->|"StatsRequest"| Switch
    Switch -->|"StatsReply"| Controller
```

**What is a Flow Table?**

Every OvS switch keeps a table of rules. Each rule says: "If a packet matches these conditions, do this action."

```
╔══════════════════════════════════════════════════════════════╗
║                    Flow Table (inside S1)                    ║
╠════════════════════╦═══════════════╦════════════════════════╣
║ Match              ║ Action        ║ Stats                  ║
╠════════════════════╬═══════════════╬════════════════════════╣
║ dst_ip=10.0.0.10   ║ → Port 2      ║ 1,200 packets, 120KB   ║
║ udp dst_port=5005  ║ (Path A)      ║                        ║
╠════════════════════╬═══════════════╬════════════════════════╣
║ dst_ip=10.0.0.11   ║ → Port 3      ║ 850 packets, 18MB      ║
║ tcp dst_port=5007  ║ (Path B)      ║                        ║
╠════════════════════╬═══════════════╬════════════════════════╣
║ (anything else)    ║ → Controller  ║ 42 packets             ║
║                    ║ (table-miss)  ║                        ║
╚════════════════════╩═══════════════╩════════════════════════╝
```

---

## 13. Training the AI — The Learning Loop

Before the demo, we need to train the AI. Here's the full loop:

```mermaid
flowchart TD
    Start["Start Training\n(ε = 1.0, random actions)"]
    
    GetState["Get current network state\n[link utils, queues, delay, flow_type]"]
    
    Action["AI picks action\n(ε-greedy: random or best Q)"]
    
    Install["Install routing rule\nin the switch"]
    
    Wait["Wait for flow to complete\n(or timeout after 30s)"]
    
    Reward["Calculate reward:\n✅ fast flow → +1.0\n❌ packet loss → -1.0\n⏱️ slow flow → +0.1"]
    
    Store["Store experience in memory\n(state, action, reward, next_state)"]
    
    Enough{{"Memory has\n>64 experiences?"}}
    
    Train["Sample 64 random experiences\nUpdate neural network weights\nusing Bellman equation"]
    
    Decay["Decrease ε by 0.5%\n(slightly less random next time)"]
    
    Done{{"ε < 0.01?\n(trained enough?)"}}
    
    Save["Save model weights\nto model_weights.pth"]
    Deploy["Deploy: AI routes\nlive traffic"]
    
    Start --> GetState --> Action --> Install --> Wait --> Reward --> Store --> Enough
    Enough -->|"No"| GetState
    Enough -->|"Yes"| Train --> Decay --> Done
    Done -->|"No"| GetState
    Done -->|"Yes"| Save --> Deploy
```

**How long does training take?**

In a Mininet simulation, one "episode" (one flow from start to finish) takes about 2–5 seconds. With ~2000 episodes needed, that's roughly **2–3 hours of training**. We run this overnight and load the saved weights for the demo.

---

## 14. The Monitoring Dashboard

While everything runs, we have a live web dashboard showing exactly what's happening.

```mermaid
graph LR
    subgraph "Data Sources"
        OvS_Stats["OvS Switch Stats\n(bytes/sec per port)"]
        Ryu_Events["Ryu Controller Events\n(new flows, route decisions)"]
        AI_State["AI Agent State\n(epsilon, last action, reward)"]
    end

    subgraph "Backend"
        Collector["Stats Collector\n(polls OvS every 2 seconds)"]
        FlaskWS["Flask + WebSocket Server\n(pushes updates to browser)"]
    end

    subgraph "Frontend"
        Topo["Network Topology\n(D3.js — live graph showing\nwhich links are busy)"]
        Charts["Live Charts\n(throughput, latency,\npacket loss over time)"]
        Flows["Active Flows Table\n(what's routing where\nand why)"]
    end

    OvS_Stats --> Collector
    Ryu_Events --> FlaskWS
    AI_State --> FlaskWS
    Collector --> FlaskWS
    FlaskWS -->|"WebSocket push\nevery 2 seconds"| Topo
    FlaskWS --> Charts
    FlaskWS --> Flows
```

**What the dashboard shows:**

- 🔴 Red links = congested (>70% utilization)
- 🟡 Yellow links = moderate (30–70%)
- 🟢 Green links = free (<30%)
- Arrows showing which path each active flow is using
- Real-time latency graph for the sensor data
- AI epsilon value (showing training progress)

---

## 15. The Experiments — How We Prove It Works

We run 9 experiments: 3 routing policies × 3 traffic scenarios.

```mermaid
graph TB
    subgraph Policies["3 Routing Policies"]
        P1["📍 Shortest Path\n(always same road)"]
        P2["⚖️ ECMP\n(round-robin)"]
        P3["🤖 AI / DQN\n(smart routing)"]
    end

    subgraph Scenarios["3 Traffic Scenarios"]
        SC1["🟦 Uniform\nAll small sensor flows\nLight load, easy case"]
        SC2["🟧 Elephant\nSensors + one huge\nbulk transfer"]
        SC3["🟥 Adversarial\nVideo + sensors +\nelephant, all at once"]
    end

    subgraph Metrics["📊 What We Measure"]
        M1["Flow Completion Time\nHow long did it take?\nLower = better"]
        M2["Throughput (Mbps)\nHow much data got through?\nHigher = better"]
        M3["Packet Loss (%)\nHow much data was dropped?\nLower = better"]
        M4["Latency (ms)\nEnd-to-end delay\nLower = better"]
    end

    Policies --> Metrics
    Scenarios --> Metrics
```

**Expected results — what we expect to see:**

```mermaid
xychart-beta
    title "Expected: Avg Flow Completion Time (lower is better)"
    x-axis ["Uniform", "Elephant Flow", "Adversarial"]
    y-axis "Time (seconds)" 0 --> 20
    bar [2, 5, 4]
    bar [2, 4, 3]
    bar [2, 2, 2]
```

*Bar order: Shortest Path (high), ECMP (medium), AI (low)*

The key insight the experiment proves: in easy conditions (uniform traffic), all three policies perform similarly. The AI's advantage only shows clearly under **stress** — when the elephant flow appears and the adversarial scenario creates real congestion. That's when dumb routing breaks down and smart routing shines.

---

## 16. The Final Demo — What the Audience Sees

The demo tells a story. Here's the narrative arc:

```mermaid
timeline
    title Demo Story Arc

    section Phase 1 — Calm
        Sensors running : Small packets flowing every 5 seconds
                        : Latency is low (< 5ms)
                        : All policies perform well
                        : "Everything looks fine"

    section Phase 2 — Stress
        Video stream added : 3 Mbps continuous flow starts
                           : Network starts to fill up
                           : Shortest path latency creeps up
                           : AI notices, prepares to reroute

    section Phase 3 — Crisis
        Elephant flow injected : 500MB bulk download starts
                               : Path A → CONGESTED 🔴
                               : Shortest path : sensor latency spikes to 200ms
                               : ECMP : moderate degradation
                               : AI : shifts sensors to Path B, latency stays < 10ms ✅

    section Phase 4 — Recovery
        Elephant flow ends : Congestion clears
                           : AI gradually migrates flows back to Path A
                           : Network stabilises
```

**The live demonstration steps:**

1. Open dashboard in browser — show the live network topology
2. Start sensor traffic — show green links, low latency chart
3. Start video stream — show one link turn yellow
4. Switch routing mode to "Shortest Path" — inject elephant flow — watch the dashboard turn red, latency chart spike
5. Switch routing mode to "AI" — inject elephant flow again — watch AI move flows to Path B, latency stays flat
6. Point out the AI epsilon on screen — show it's not randomly exploring, it's using learned knowledge

---

## 17. How Everything Connects — The Big Picture

Here is the complete flow of the entire system from start to finish, all on one diagram:

```mermaid
flowchart TB
    subgraph Physical["🌍 Physical World"]
        ESP["ESP32\nsends real sensor data"]
    end

    subgraph Laptop["💻 Laptop — Edge"]
        MN_Host["Mininet Virtual Host\n(simulates more IoT devices)"]
        OvS_SW["Open vSwitch\n(forwards packets)\nHolds flow table rules"]
    end

    subgraph CloudVM["☁️ Cloud VM — Intelligence"]
        RyuCtrl["Ryu Controller\n• Manages switch connections\n• Handles PacketIn events\n• Installs FlowMod rules"]
        FlaskAPI["Flask REST API\n• Bridge between Ryu & AI\n• Exposes /api/routing endpoint"]
        DQNModel["DQN AI Agent\n• Neural network (PyTorch)\n• Reads network state\n• Outputs best path action\n• Learns from rewards"]
        StatsDB["Statistics Store\n• Link utilizations\n• Queue lengths\n• Packet delays"]
    end

    subgraph Browser["🌐 Browser — Visibility"]
        Dash["Live Dashboard\n• Network topology map\n• Real-time charts\n• Routing decisions log"]
    end

    ESP -->|"UDP packets\nover WiFi"| OvS_SW
    MN_Host -->|"virtual packets"| OvS_SW

    OvS_SW -->|"PacketIn\n(unknown flow)"| RyuCtrl
    RyuCtrl -->|"FlowMod\n(install rule)"| OvS_SW
    OvS_SW -->|"port statistics\nevery 2s"| StatsDB

    RyuCtrl -->|"ask: what path?\nPOST /api/routing"| FlaskAPI
    FlaskAPI -->|"get state\ncall select_action"| DQNModel
    DQNModel -->|"action: path 1/2/3"| FlaskAPI
    FlaskAPI -->|"return port number"| RyuCtrl

    RyuCtrl -->|"submit reward\nafter flow ends"| FlaskAPI
    FlaskAPI -->|"store experience\ncall train()"| DQNModel

    StatsDB -->|"state vector\n[utils, queues, delay]"| DQNModel
    StatsDB -->|"WebSocket push"| Dash
    RyuCtrl -->|"flow events"| Dash

    style Physical fill:#1a1a2e,color:#eee
    style Laptop fill:#16213e,color:#eee
    style CloudVM fill:#0f3460,color:#eee
    style Browser fill:#1b2631,color:#eee
```

### Summary — What Each Component Owns

| Component | Lives On | Does What |
|---|---|---|
| ESP32 / IoT Device | Physical hardware | Generates real traffic |
| Mininet | Laptop | Simulates extra IoT devices and network |
| Open vSwitch | Laptop | Acts as the programmable network switch |
| Ryu Controller | Cloud VM | Manages switches, handles new flows |
| Flask REST API | Cloud VM | Connects controller to AI agent |
| DQN AI Agent | Cloud VM | Decides which path to use, learns over time |
| Stats Collector | Laptop/VM | Measures link utilization, delay, queues |
| Dashboard | Cloud VM (browser) | Shows everything in real time |

### The Three Questions — Answered Simply

**Q: What is the system doing?**
Routing IoT network traffic intelligently — sending different types of traffic down different network paths based on live conditions, not just shortest distance.

**Q: How does it do it?**
An AI agent watches the network state, picks the best path for each flow, installs that as a rule in the switch, and learns from whether that was a good or bad choice.

**Q: Why is it better?**
Because it adapts. When an elephant flow congests one path, the AI detects this and moves critical traffic to the other path — something no static routing algorithm can do.

---

*"The goal isn't just to build a network that works. It's to build one that thinks."*

---

*Simple Explainer v1.0 — AI-Driven SDN for IoT*
