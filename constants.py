"""
Shared constants for the entire project.
ALL teams import from here — never hard-code these values elsewhere.
"""

# ── Controller ────────────────────────────────────────────────────────────────
CONTROLLER_HOST = "127.0.0.1"
CONTROLLER_PORT = 6633

# ── Switch names ──────────────────────────────────────────────────────────────
# s1, s2 = access layer (IoT clusters A and B)
# s3     = core switch, low-latency path
# s4     = core switch, high-bandwidth path
# s5     = aggregation / server switch
SWITCHES = ["s1", "s2", "s3", "s4", "s5"]

# ── Port assignments ──────────────────────────────────────────────────────────
# Mininet assigns ports in link-creation order (see iot_topology.py).
# These are the uplink ports on each access switch toward the core.

# S1 (Cluster A access switch)
S1_PORT_SENSOR1   = 1   # h_sensor1
S1_PORT_SENSOR2   = 2   # h_sensor2
S1_PORT_CAMERA1   = 3   # h_camera1
S1_PORT_EMERGENCY = 4   # h_emergency
S1_PORT_CORE_A    = 5   # → s3  (Path A, low latency)
S1_PORT_CORE_B    = 6   # → s4  (Path B, high BW)

# S2 (Cluster B access switch)
S2_PORT_SENSOR3   = 1   # h_sensor3
S2_PORT_SENSOR4   = 2   # h_sensor4
S2_PORT_CAMERA2   = 3   # h_camera2
S2_PORT_ACTUATOR  = 4   # h_actuator
S2_PORT_CORE_A    = 5   # → s3
S2_PORT_CORE_B    = 6   # → s4

# S3 (Core, low-latency)
S3_PORT_FROM_S1   = 1
S3_PORT_FROM_S2   = 2
S3_PORT_TO_S5     = 3   # → s5 (50 Mbps, 2ms)
S3_PORT_CROSSLINK = 4   # ↔ s4 (cross-link, 50 Mbps, 3ms)

# S4 (Core, high-BW)
S4_PORT_FROM_S1   = 1
S4_PORT_FROM_S2   = 2
S4_PORT_TO_S5     = 3   # → s5 (100 Mbps, 5ms)
S4_PORT_CROSSLINK = 4   # ↔ s3

# S5 (Aggregation / server switch)
S5_PORT_FROM_S3   = 1
S5_PORT_FROM_S4   = 2
S5_PORT_SERVER1   = 3
S5_PORT_SERVER2   = 4

# ── Link capacities (Mbps) ────────────────────────────────────────────────────
LINK_BW_SENSOR       = 1
LINK_BW_CAMERA       = 10
LINK_BW_ACTUATOR     = 2
LINK_BW_EMERGENCY    = 2
LINK_BW_ACCESS_CORE  = 20    # S1/S2 → S3/S4
LINK_BW_CORE_SERVER_A = 50   # S3 → S5
LINK_BW_CORE_SERVER_B = 100  # S4 → S5 (higher BW)
LINK_BW_CROSSLINK    = 50    # S3 ↔ S4
LINK_BW_SERVER       = 1000  # S5 → servers

# ── Link delays ───────────────────────────────────────────────────────────────
LINK_DELAY_SENSOR       = "2ms"
LINK_DELAY_CAMERA       = "5ms"
LINK_DELAY_ACTUATOR     = "1ms"
LINK_DELAY_EMERGENCY    = "1ms"
LINK_DELAY_S1_S3        = "5ms"    # Cluster A → core low-latency
LINK_DELAY_S1_S4        = "8ms"    # Cluster A → core high-BW
LINK_DELAY_S2_S3        = "6ms"    # Cluster B → core low-latency
LINK_DELAY_S2_S4        = "7ms"    # Cluster B → core high-BW
LINK_DELAY_S3_S5        = "2ms"    # Core A → server
LINK_DELAY_S4_S5        = "5ms"    # Core B → server
LINK_DELAY_CROSSLINK    = "3ms"    # S3 ↔ S4
LINK_DELAY_SERVER       = "1ms"

# ── Host IPs ──────────────────────────────────────────────────────────────────
# Cluster A (→ s1)
IP_SENSOR1    = "10.0.0.1"
IP_SENSOR2    = "10.0.0.2"
IP_CAMERA1    = "10.0.0.3"
IP_EMERG      = "10.0.0.4"
# Cluster B (→ s2)
IP_SENSOR3    = "10.0.0.5"
IP_SENSOR4    = "10.0.0.6"
IP_CAMERA2    = "10.0.0.7"
IP_ACTUATOR   = "10.0.0.8"
# Servers (→ s5)
IP_SERVER1    = "10.0.0.9"
IP_SERVER2    = "10.0.0.10"

# Cluster IP ranges (for flow classification)
CLUSTER_A_IPS = {IP_SENSOR1, IP_SENSOR2, IP_CAMERA1, IP_EMERG}
CLUSTER_B_IPS = {IP_SENSOR3, IP_SENSOR4, IP_CAMERA2, IP_ACTUATOR}
EMERGENCY_IPS = {IP_EMERG}
ACTUATOR_IPS  = {IP_ACTUATOR}

# ── Traffic classification ────────────────────────────────────────────────────
SENSOR_PORT   = 5005   # UDP — low-bandwidth periodic readings
VIDEO_PORT    = 5006   # UDP — continuous stream
ELEPHANT_PORT = 5007   # TCP — bulk transfer
ACTUATOR_PORT = 5008   # UDP — low-latency control commands

DSCP_EMERGENCY = 46    # EF — highest priority (emergency + actuator)
DSCP_SENSOR    = 34    # AF41 — sensor readings
DSCP_VIDEO     = 26    # AF31 — video stream
DSCP_ELEPHANT  = 0     # BE  — bulk transfer

# ── DQN actions ───────────────────────────────────────────────────────────────
ACTION_PATH_A  = 0   # Via s3 → s5 (low latency, 7ms end-to-end)
ACTION_PATH_B  = 1   # Via s4 → s5 (high BW, 13ms end-to-end)
ACTION_PATH_C  = 2   # Via s3 → s4 → s5 (cross-link overflow, 13ms + 3ms)
ACTION_DROP    = 3
NUM_ACTIONS    = 4
ACTION_NAMES   = {
    ACTION_PATH_A: "PathA(s3,low-lat)",
    ACTION_PATH_B: "PathB(s4,high-BW)",
    ACTION_PATH_C: "PathC(cross-link)",
    ACTION_DROP:   "Drop",
}

# ── State vector — 20 features ────────────────────────────────────────────────
# Contract between stats_collector.py (M1) and dqn_agent.py (M2).
# Do NOT reorder without updating both files.
STATE_FEATURES = [
    # idx  name                       source              normalization
    (0,  "link_util_s1_s3",          "S1 port 5 stats",  "Mbps / 20.0"),
    (1,  "link_util_s1_s4",          "S1 port 6 stats",  "Mbps / 20.0"),
    (2,  "link_util_s2_s3",          "S2 port 5 stats",  "Mbps / 20.0"),
    (3,  "link_util_s2_s4",          "S2 port 6 stats",  "Mbps / 20.0"),
    (4,  "link_util_s3_s5",          "S3 port 3 stats",  "Mbps / 50.0"),
    (5,  "link_util_s4_s5",          "S4 port 3 stats",  "Mbps / 100.0"),
    (6,  "link_util_crosslink",      "S3 port 4 stats",  "Mbps / 50.0"),
    (7,  "active_flows_path_a",      "flow table s3",    "count / 20.0"),
    (8,  "active_flows_path_b",      "flow table s4",    "count / 20.0"),
    (9,  "active_flows_path_c",      "flow table s3+s4", "count / 20.0"),
    (10, "packet_loss_path_a",       "TX vs RX s3",      "[0,1]"),
    (11, "packet_loss_path_b",       "TX vs RX s4",      "[0,1]"),
    (12, "jitter_path_a",            "util variance",    "ms / 50.0"),
    (13, "jitter_path_b",            "util variance",    "ms / 50.0"),
    (14, "bytes_path_a",             "flow counters s3", "bytes / 1e7"),
    (15, "bytes_path_b",             "flow counters s4", "bytes / 1e7"),
    (16, "time_of_day",              "system clock",     "sec / 86400"),
    (17, "util_trend",               "delta avg util",   "[-1, 1]"),
    (18, "priority_flag",            "DSCP field",       "1=high-prio active"),
    (19, "congestion_flag",          "derived",          "1=any link >80%"),
]
STATE_DIM     = len(STATE_FEATURES)   # 20
FEATURE_NAMES = [f[1] for f in STATE_FEATURES]

# ── Training hyperparameters ──────────────────────────────────────────────────
SEQUENCE_LEN    = 10
REPLAY_CAPACITY = 10_000
BATCH_SIZE      = 64
GAMMA           = 0.99
LR              = 1e-4
EPS_START       = 1.0
EPS_END         = 0.01
EPS_DECAY       = 0.995
TARGET_SYNC     = 100
GRAD_CLIP_NORM  = 1.0
STATS_INTERVAL  = 2.0

# Reward weights
R_LATENCY      = 0.4
R_RELIABILITY  = 0.3
R_THROUGHPUT   = 0.2
R_FAIRNESS     = 0.1
R_PRIORITY_MUL = 5.0

# ── API ───────────────────────────────────────────────────────────────────────
API_HOST            = "127.0.0.1"
API_PORT            = 5000
API_BASE            = f"http://{API_HOST}:{API_PORT}"
DASHBOARD_PORT      = 8080
RUNTIME_STATE_FILE  = "/tmp/sdn_runtime_state.json"
REPLAY_BUFFER_FILE  = "/tmp/sdn_replay_buffer.pkl"
