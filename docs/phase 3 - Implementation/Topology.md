# Topology
### Phase 1 — 2-Tier 5-Switch IoT Network

---

## Table of Contents

- [[#Design Goals|Design Goals]]
- [[#Network Diagram|Network Diagram]]
- [[#Switch Roles|Switch Roles]]
- [[#Link Parameters|Link Parameters]]
- [[#Routing Paths|Routing Paths]]
- [[#Port Assignment Reference|Port Assignment Reference]]
- [[#Implementation Notes|Implementation Notes]]
- [[#Test Results|Test Results]]

---

## Design Goals

1. **Enough switches to make routing non-trivial** — 5 switches vs the trivial 3-switch baseline, giving the DQN meaningful choices.
2. **Asymmetric paths** — Path A is faster (lower latency), Path B has higher bandwidth; the DQN must learn when each matters.
3. **Cross-link overflow** — S3↔S4 allows a third path when both primary paths are congested.
4. **Realistic IoT device mix** — sensors (low BW, periodic), cameras (medium BW, continuous), emergency/actuator (low BW, latency-critical).

---

## Network Diagram

```
  CLUSTER A                          CLUSTER B
  ─────────                          ─────────
  h_sensor1  (1M, 2ms) ─┐           h_sensor3  (1M, 2ms) ─┐
  h_sensor2  (1M, 2ms) ─┤           h_sensor4  (1M, 2ms) ─┤
  h_camera1  (10M, 5ms)─┤           h_camera2  (10M, 5ms)─┤
  h_emerg    (2M, 1ms) ─┘           h_actuator (2M, 1ms) ─┘
             │                                 │
             ▼                                 ▼
          [ S1 ]                           [ S2 ]
         /       \                         /      \
  (20M,5ms)  (20M,8ms)             (20M,6ms)  (20M,7ms)
       /           \               /               \
    [ S3 ]──────────────────────[ S4 ]
  (50M,3ms cross-link, 3ms)
    [ S3 ]                       [ S4 ]
  (50M,2ms)                    (100M,5ms)
       \                           /
        └────────── [ S5 ] ────────┘
                  h_server1 (1G, 1ms)
                  h_server2 (1G, 1ms)
```

**End-to-end latency estimates (one-way):**
- Path A (Cluster A → S3 → S5): 2ms + 5ms + 2ms + 1ms = **10 ms**
- Path B (Cluster A → S4 → S5): 2ms + 8ms + 5ms + 1ms = **16 ms**
- Path C (Cluster A → S3 → S4 → S5): 2ms + 5ms + 3ms + 5ms + 1ms = **16 ms**

---

## Switch Roles

| Switch | Layer | Role |
|--------|-------|------|
| **S1** | Access | Cluster A aggregation — connects 4 IoT devices, dual uplinks to core |
| **S2** | Access | Cluster B aggregation — same structure as S1 |
| **S3** | Core | Low-latency path — 50 Mbps to S5, lower delay links from S1/S2 |
| **S4** | Core | High-bandwidth path — 100 Mbps to S5, higher delay links from S1/S2 |
| **S5** | Aggregation | Server distribution — connects h_server1 and h_server2 at 1 Gbps each |

---

## Link Parameters

| Link | BW (Mbps) | Delay | Queue |
|------|-----------|-------|-------|
| Sensor → S1/S2 | 1 | 2 ms | 100 pkts |
| Camera → S1/S2 | 10 | 5 ms | 500 pkts |
| Emerg/Actuator → S1/S2 | 2 | 1 ms | 50 pkts |
| S1 → S3 | 20 | 5 ms | 2000 pkts |
| S1 → S4 | 20 | 8 ms | 2000 pkts |
| S2 → S3 | 20 | 6 ms | 2000 pkts |
| S2 → S4 | 20 | 7 ms | 2000 pkts |
| S3 → S5 | 50 | 2 ms | 5000 pkts |
| S4 → S5 | 100 | 5 ms | 5000 pkts |
| S3 ↔ S4 (cross-link) | 50 | 3 ms | 3000 pkts |
| S5 → h_server1/2 | 1000 | 1 ms | 10000 pkts |

Queue sizes are set via `max_queue_size` in TCLink and influence packet drop under congestion.

---

## Routing Paths

The DQN chooses one of four actions for each new IoT→server flow:

| Action | Hops | Best for |
|--------|------|---------|
| **PATH_A** (via S3) | S1/S2 → S3 → S5 | Low-latency flows: emergency, actuator, small sensor bursts |
| **PATH_B** (via S4) | S1/S2 → S4 → S5 | High-bandwidth flows: video streams, elephant bulk transfers |
| **PATH_C** (cross-link) | S1/S2 → S3 → S4 → S5 | Overflow: when PATH_A is congested and PATH_B is also busy |
| **DROP** | — | Low-priority flows under extreme congestion |

PATH_C uses the S3→S4 cross-link (port 4 on both switches), then exits via S4→S5. It avoids using the direct S1/S2→S4 uplinks, so it does not compete with PATH_B on the access side.

---

## Port Assignment Reference

Mininet assigns ports in the order that `addLink()` is called. The port map is therefore deterministic and matches `constants.py`:

```
S1 port 1 = h_sensor1      S2 port 1 = h_sensor3
S1 port 2 = h_sensor2      S2 port 2 = h_sensor4
S1 port 3 = h_camera1      S2 port 3 = h_camera2
S1 port 4 = h_emerg        S2 port 4 = h_actuator
S1 port 5 = → S3           S2 port 5 = → S3
S1 port 6 = → S4           S2 port 6 = → S4

S3 port 1 = ← S1           S4 port 1 = ← S1
S3 port 2 = ← S2           S4 port 2 = ← S2
S3 port 3 = → S5 (50M)     S4 port 3 = → S5 (100M)
S3 port 4 = ↔ S4 crosslink  S4 port 4 = ↔ S3 crosslink

S5 port 1 = ← S3           S5 port 3 = → h_server1
S5 port 2 = ← S4           S5 port 4 = → h_server2
```

---

## Implementation Notes

**`IoTTopo.build(fail_mode, stp)`**  
The build method accepts two parameters to support both Ryu and standalone (testing) modes:

- `fail_mode="secure"` — used with Ryu: switches drop all packets without a matching flow rule (correct SDN behaviour)
- `fail_mode="standalone"` — used without Ryu: OvS acts as a standard learning switch, allowing pingall tests without a controller
- `stp=True` — enabled only in standalone mode to prevent broadcast storms caused by the S3↔S4 loop

**OVSController fallback in `build_net()`**  
`build_net()` probes `CONTROLLER_HOST:CONTROLLER_PORT` before starting. If Ryu is not reachable, it falls back to OVSController with `fail_mode="standalone"` and `stp=True`, and the test path waits 35 s for STP convergence.

**`autoSetMacs=True`**  
Mininet auto-assigns MAC addresses from host numbers. This prevents ARP conflicts and allows OvS to learn MACs without manual configuration.

**`autoStaticArp=True`**  
Pre-populates ARP tables for all host pairs, eliminating ARP flooding during tests.

---

## Test Results

```
sudo .venv/bin/python3 mininet/iot_topology.py --test

*** Ryu not reachable — falling back to OVSController (standalone mode)
*** Creating network
*** Adding hosts: h_actuator h_camera1 h_camera2 h_emerg
                  h_sensor1 h_sensor2 h_sensor3 h_sensor4
                  h_server1 h_server2
*** Adding switches: s1 s2 s3 s4 s5
*** Adding links: [17 links created with TCLink parameters]
*** Waiting 35s for STP convergence (standalone mode)...
*** Running pingall...
*** Results: 0% dropped (90/90 received)
*** Packet loss: 0.0%
```

All 10 hosts can reach all other 9 hosts (90 ordered pairs) with zero packet loss.

See also: [[Architecture]] · [[Ryu_Controller]] · [[Implementation_Overview]]
