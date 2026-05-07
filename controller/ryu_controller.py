"""
Phase 5 — Ryu SDN Controller with Dueling LSTM-DQN routing.

Run (from project root, in native terminal with Ryu installed):
    ryu-manager controller/ryu_controller.py

Architecture:
  - PacketIn  : classify new flow → query DQN → install OpenFlow rules on 4-5 switches
  - Stats loop: every STATS_INTERVAL s → build 20-feature state → compute reward
                → agent.store() → agent.learn() → save weights periodically
  - Static    : table-miss (send-to-controller) on all switches; S5 server distribution
"""

import json
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, tcp, udp, ether_types
from ryu.lib import hub

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from constants import (
    # Dims / hyper
    STATE_DIM, SEQUENCE_LEN, STATS_INTERVAL,
    # Port assignments
    S1_PORT_SENSOR1, S1_PORT_SENSOR2, S1_PORT_CAMERA1, S1_PORT_EMERGENCY,
    S1_PORT_CORE_A, S1_PORT_CORE_B,
    S2_PORT_SENSOR3, S2_PORT_SENSOR4, S2_PORT_CAMERA2, S2_PORT_ACTUATOR,
    S2_PORT_CORE_A, S2_PORT_CORE_B,
    S3_PORT_FROM_S1, S3_PORT_FROM_S2, S3_PORT_TO_S5, S3_PORT_CROSSLINK,
    S4_PORT_FROM_S1, S4_PORT_FROM_S2, S4_PORT_TO_S5, S4_PORT_CROSSLINK,
    S5_PORT_FROM_S3, S5_PORT_FROM_S4, S5_PORT_SERVER1, S5_PORT_SERVER2,
    # Host IPs
    IP_SENSOR1, IP_SENSOR2, IP_CAMERA1, IP_EMERG,
    IP_SENSOR3, IP_SENSOR4, IP_CAMERA2, IP_ACTUATOR,
    IP_SERVER1, IP_SERVER2,
    CLUSTER_A_IPS, CLUSTER_B_IPS, EMERGENCY_IPS, ACTUATOR_IPS,
    # Traffic classification
    SENSOR_PORT, VIDEO_PORT, ELEPHANT_PORT, ACTUATOR_PORT,
    DSCP_EMERGENCY,
    # Actions
    ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C, ACTION_DROP, ACTION_NAMES,
    # Comparison mode
    ROUTING_MODE_DQN, ROUTING_MODE_BASELINE, BASELINE_POLICY_DEFAULT,
)
from agent.dqn_agent import DQNAgent, compute_reward
from collector.stats_collector import StatsCollector
from constants import FEATURE_NAMES, RUNTIME_STATE_FILE, REPLAY_BUFFER_FILE
from controller.baseline_router import (
    BaselineRouter,
    BASELINE_POLICIES,
)
import api.shared_state as shared_state

# ── Constants ─────────────────────────────────────────────────────────────────

WEIGHTS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "model_weights.pth")
SAVE_EVERY   = 200      # save weights every N learning steps

# Datapath IDs — Mininet assigns 1-5 for s1-s5
DPID_S1, DPID_S2, DPID_S3, DPID_S4, DPID_S5 = 1, 2, 3, 4, 5

SERVER_IPS = {IP_SERVER1, IP_SERVER2}
IOT_IPS    = CLUSTER_A_IPS | CLUSTER_B_IPS

# Flow timeouts (seconds)
FLOW_IDLE = 10
FLOW_HARD = 60

# Priority levels for OpenFlow rules
PRIO_TABLE_MISS = 0
PRIO_STATIC     = 10
PRIO_FLOW       = 100
PRIO_EMERGENCY  = 200

# Host IP → (access_switch_dpid, host_port_on_switch)
HOST_PORT = {
    IP_SENSOR1:  (DPID_S1, S1_PORT_SENSOR1),
    IP_SENSOR2:  (DPID_S1, S1_PORT_SENSOR2),
    IP_CAMERA1:  (DPID_S1, S1_PORT_CAMERA1),
    IP_EMERG:    (DPID_S1, S1_PORT_EMERGENCY),
    IP_SENSOR3:  (DPID_S2, S2_PORT_SENSOR3),
    IP_SENSOR4:  (DPID_S2, S2_PORT_SENSOR4),
    IP_CAMERA2:  (DPID_S2, S2_PORT_CAMERA2),
    IP_ACTUATOR: (DPID_S2, S2_PORT_ACTUATOR),
}

# ── Flow tracking ─────────────────────────────────────────────────────────────

@dataclass
class FlowEntry:
    action:     int
    state_seq:  list          # state sequence when DQN made the decision
    start_time: float = field(default_factory=time.time)
    is_priority: bool = False


# ── Controller ────────────────────────────────────────────────────────────────

class IoTController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.datapaths: dict[int, object] = {}

        mode = os.getenv("SDN_ROUTING_MODE", ROUTING_MODE_DQN).strip().lower()
        if mode not in {ROUTING_MODE_DQN, ROUTING_MODE_BASELINE}:
            mode = ROUTING_MODE_DQN
        self.routing_mode = mode

        policy = os.getenv("SDN_BASELINE_POLICY", BASELINE_POLICY_DEFAULT).strip().lower()
        if policy not in BASELINE_POLICIES:
            policy = BASELINE_POLICY_DEFAULT
        self.baseline_policy = policy
        self.shadow_compare_enabled = os.getenv("SDN_COMPARE_SHADOW", "1").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.baseline_router = BaselineRouter(
            policy=self.baseline_policy,
            seed=int(os.getenv("SDN_BASELINE_SEED", "42")),
        )

        # flow_key = (ip_src, ip_dst) → FlowEntry
        self.flow_table: dict[tuple, FlowEntry] = {}
        # Shadow flow table for non-active policy in comparison mode.
        self.shadow_flow_table: dict[tuple, FlowEntry] = {}

        # Count of active flows per action/path (actual policy + comparison policy).
        self.dqn_path_counts: dict[int, int] = {
            ACTION_PATH_A: 0, ACTION_PATH_B: 0, ACTION_PATH_C: 0, ACTION_DROP: 0,
        }
        self.baseline_path_counts: dict[int, int] = {
            ACTION_PATH_A: 0, ACTION_PATH_B: 0, ACTION_PATH_C: 0, ACTION_DROP: 0,
        }
        self.path_counts = (
            self.dqn_path_counts if self.routing_mode == ROUTING_MODE_DQN else self.baseline_path_counts
        )

        # Rolling LSTM input buffer (seq_len snapshots of the 20-feature state)
        self.state_buffer: deque = deque(
            [[0.0] * STATE_DIM for _ in range(SEQUENCE_LEN)],
            maxlen=SEQUENCE_LEN,
        )
        self.prev_state: list[float] = [0.0] * STATE_DIM

        # DQN agent
        self.agent = DQNAgent()
        if os.path.exists(WEIGHTS_PATH):
            self.agent.load(WEIGHTS_PATH)
            self.logger.info("Loaded weights from %s", WEIGHTS_PATH)
        if os.path.exists(REPLAY_BUFFER_FILE):
            n = self.agent.load_buffer(REPLAY_BUFFER_FILE)
            self.logger.info("Loaded replay buffer: %d experiences", n)

        # Stats collector (polls OvS switches)
        self.collector = StatsCollector()

        # Training counters
        self.learn_steps = 0
        self.total_reward = 0.0
        self.dqn_total_reward = 0.0
        self.baseline_total_reward = 0.0

        self.logger.info(
            "Routing mode=%s baseline=%s shadow_compare=%s",
            self.routing_mode,
            self.baseline_policy,
            self.shadow_compare_enabled,
        )

        hub.spawn(self._stats_loop)

    # ── OpenFlow event: switch connects ──────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        self.logger.info("Switch connected: dpid=%d", dp.id)
        self._install_table_miss(dp)
        if dp.id == DPID_S5:
            self._install_s5_static(dp)

    # ── OpenFlow event: unknown packet arrives ────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg      = ev.msg
        dp       = msg.datapath
        in_port  = msg.match["in_port"]
        pkt      = packet.Packet(msg.data)

        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype != ether_types.ETH_TYPE_IP:
            return          # ignore non-IP (ARP handled by flood below)

        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt is None:
            return

        src_ip = ip_pkt.src
        dst_ip = ip_pkt.dst

        # ── ARP / unknown source: flood and return ────────────────────────────
        if src_ip not in IOT_IPS and src_ip not in SERVER_IPS:
            self._flood(dp, msg, in_port)
            return

        # ── Return traffic (server → IoT): install static return rules ────────
        if src_ip in SERVER_IPS and dst_ip in IOT_IPS:
            self._install_return_rules(src_ip, dst_ip)
            self._packet_out(dp, msg, in_port)
            return

        # ── Forward traffic (IoT → server): DQN decides ───────────────────────
        if src_ip not in IOT_IPS or dst_ip not in SERVER_IPS:
            self._flood(dp, msg, in_port)
            return

        flow_key = (src_ip, dst_ip)
        if flow_key in self.flow_table:
            return          # rules already installed for this flow

        is_priority = (src_ip in EMERGENCY_IPS or src_ip in ACTUATOR_IPS)
        state_seq   = list(self.state_buffer)

        dqn_action = self._enforce_priority_action(
            self.agent.select_action(state_seq), is_priority
        )
        baseline_action = self._enforce_priority_action(
            self.baseline_router.select_action(
                flow_key=flow_key,
                state=state_seq[-1],
                path_counts=self.baseline_path_counts,
            ),
            is_priority,
        )
        action = dqn_action if self.routing_mode == ROUTING_MODE_DQN else baseline_action
        shadow_action = baseline_action if self.routing_mode == ROUTING_MODE_DQN else dqn_action

        self.flow_table[flow_key] = FlowEntry(
            action=action,
            state_seq=state_seq,
            is_priority=is_priority,
        )
        self.path_counts[action] = self.path_counts.get(action, 0) + 1

        if self.shadow_compare_enabled:
            self.shadow_flow_table[flow_key] = FlowEntry(
                action=shadow_action,
                state_seq=state_seq,
                is_priority=is_priority,
            )
            shadow_counts = (
                self.baseline_path_counts
                if self.routing_mode == ROUTING_MODE_DQN
                else self.dqn_path_counts
            )
            shadow_counts[shadow_action] = shadow_counts.get(shadow_action, 0) + 1

        self.logger.info(
            "New flow %s→%s | mode=%s action=%s | dqn=%s baseline=%s ε=%.3f",
            src_ip, dst_ip, self.routing_mode, ACTION_NAMES[action],
            ACTION_NAMES[dqn_action], ACTION_NAMES[baseline_action], self.agent.epsilon,
        )

        if action == ACTION_DROP:
            self._install_drop(dp, src_ip, dst_ip)
        else:
            self._install_forward_rules(src_ip, dst_ip, action, is_priority)
            self._install_return_rules(dst_ip, src_ip)

        # Emit the buffered packet so it isn't lost while rules install
        self._packet_out(dp, msg, in_port)

    # ── Background: stats polling + training ──────────────────────────────────

    def _stats_loop(self):
        """Polls OvS every STATS_INTERVAL seconds, builds state, trains agent."""
        hub.sleep(3)    # let all switches connect first
        while True:
            try:
                new_state = self.collector.get_state()
            except Exception as exc:
                self.logger.warning("Stats poll failed: %s", exc)
                hub.sleep(STATS_INTERVAL)
                continue

            # Inject live path counts into the state vector (features 7-9)
            new_state = list(new_state)
            new_state[7]  = min(self.path_counts.get(ACTION_PATH_A, 0) / 20.0, 1.0)
            new_state[8]  = min(self.path_counts.get(ACTION_PATH_B, 0) / 20.0, 1.0)
            new_state[9]  = min(self.path_counts.get(ACTION_PATH_C, 0) / 20.0, 1.0)

            # Priority flag: any high-priority flow currently active
            new_state[18] = 1.0 if any(
                e.is_priority for e in self.flow_table.values()
            ) else 0.0

            self.state_buffer.append(new_state)
            next_state_seq = list(self.state_buffer)

            # ── Train on each active flow ──────────────────────────────────────
            for flow_key, entry in list(self.flow_table.items()):
                reward = compute_reward(entry.state_seq[-1], entry.action, new_state)
                if self.routing_mode == ROUTING_MODE_DQN:
                    self.agent.store(
                        entry.state_seq, entry.action, reward, next_state_seq, done=False
                    )
                    self.dqn_total_reward += reward
                else:
                    self.baseline_total_reward += reward
                # Update the entry's state_seq to slide the window forward
                entry.state_seq = next_state_seq

            for flow_key, entry in list(self.shadow_flow_table.items()):
                shadow_reward = compute_reward(entry.state_seq[-1], entry.action, new_state)
                if self.routing_mode == ROUTING_MODE_DQN:
                    self.baseline_total_reward += shadow_reward
                else:
                    self.dqn_total_reward += shadow_reward
                entry.state_seq = next_state_seq

            loss = None
            if self.routing_mode == ROUTING_MODE_DQN:
                loss = self.agent.learn()
                if loss is not None:
                    self.learn_steps += 1
                    if self.learn_steps % 10 == 0:
                        self.logger.info(
                            "Train step=%d | loss=%.4f | ε=%.4f | dqn_reward=%.2f baseline_reward=%.2f",
                            self.learn_steps, loss, self.agent.epsilon,
                            self.dqn_total_reward, self.baseline_total_reward,
                        )

            # Save every stats cycle so progress is never lost between runs
            if self.routing_mode == ROUTING_MODE_DQN:
                self.agent.save(WEIGHTS_PATH)
                self.agent.save_buffer(REPLAY_BUFFER_FILE)

            self.total_reward = (
                self.dqn_total_reward
                if self.routing_mode == ROUTING_MODE_DQN
                else self.baseline_total_reward
            )
            comparison_payload = self._build_comparison_payload()

            # ── Push to Flask API shared state ────────────────────────────────
            shared_state.push_state(new_state, FEATURE_NAMES)
            shared_state.push_agent(
                self.agent.epsilon, self.learn_steps, self.total_reward, loss
            )
            shared_state.push_path_counts(self.path_counts)
            shared_state.push_flows(self.flow_table)
            shared_state.push_comparison(comparison_payload)
            avg_util = sum(new_state[:7]) / 7
            shared_state.push_util(avg_util)

            # ── Write metrics to file for cross-process Flask API ─────────────
            self._write_state_file(new_state, loss, avg_util, comparison_payload)

            self.prev_state = new_state
            hub.sleep(STATS_INTERVAL)

    # ── OpenFlow rule installation helpers ────────────────────────────────────

    def _install_forward_rules(self, src_ip: str, dst_ip: str,
                               action: int, is_priority: bool):
        """Install FlowMod rules on every hop for the chosen path."""
        prio = PRIO_EMERGENCY if is_priority else PRIO_FLOW
        src_cluster_a = src_ip in CLUSTER_A_IPS

        # ── Access switch (S1 or S2) ──────────────────────────────────────────
        access_dpid = DPID_S1 if src_cluster_a else DPID_S2
        core_port   = (
            (S1_PORT_CORE_A if src_cluster_a else S2_PORT_CORE_A)
            if action in (ACTION_PATH_A, ACTION_PATH_C)
            else
            (S1_PORT_CORE_B if src_cluster_a else S2_PORT_CORE_B)
        )
        self._flow_mod(access_dpid, src_ip, dst_ip, core_port, prio)

        # ── Core switch ───────────────────────────────────────────────────────
        if action == ACTION_PATH_A:
            # S3 → S5
            self._flow_mod(DPID_S3, src_ip, dst_ip, S3_PORT_TO_S5, prio)

        elif action == ACTION_PATH_B:
            # S4 → S5
            self._flow_mod(DPID_S4, src_ip, dst_ip, S4_PORT_TO_S5, prio)

        elif action == ACTION_PATH_C:
            # S3 → S4 (crosslink) → S5
            self._flow_mod(DPID_S3, src_ip, dst_ip, S3_PORT_CROSSLINK, prio)
            self._flow_mod(DPID_S4, src_ip, dst_ip, S4_PORT_TO_S5,    prio)

    def _install_return_rules(self, server_ip: str, iot_ip: str):
        """Install return-path rules (server → IoT) via S3 always."""
        if not self._dp(DPID_S5):
            return

        dst_dpid, dst_host_port = HOST_PORT.get(iot_ip, (None, None))
        if dst_dpid is None:
            return

        # S5 → S3
        self._flow_mod(DPID_S5, server_ip, iot_ip, S5_PORT_FROM_S3, PRIO_STATIC)

        # S3 → S1 or S2
        s3_out = S3_PORT_FROM_S1 if dst_dpid == DPID_S1 else S3_PORT_FROM_S2
        self._flow_mod(DPID_S3, server_ip, iot_ip, s3_out, PRIO_STATIC)

        # S1/S2 → host
        self._flow_mod(dst_dpid, server_ip, iot_ip, dst_host_port, PRIO_STATIC)

    def _install_drop(self, dp, src_ip: str, dst_ip: str):
        """Install a drop rule on the access switch."""
        parser = dp.ofproto_parser
        match  = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ipv4_src=src_ip, ipv4_dst=dst_ip,
        )
        self._add_flow(dp, PRIO_FLOW, match, [], idle=FLOW_IDLE, hard=FLOW_HARD)

    def _install_s5_static(self, dp):
        """Static server-distribution rules on S5 (installed once on connect)."""
        parser = dp.ofproto_parser
        for ip, port in [(IP_SERVER1, S5_PORT_SERVER1), (IP_SERVER2, S5_PORT_SERVER2)]:
            match   = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=ip)
            actions = [parser.OFPActionOutput(port)]
            self._add_flow(dp, PRIO_STATIC, match, actions)

    def _install_table_miss(self, dp):
        ofproto = dp.ofproto
        parser  = dp.ofproto_parser
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(dp, PRIO_TABLE_MISS, match, actions)

    # ── Low-level helpers ─────────────────────────────────────────────────────

    def _flow_mod(self, dpid: int, src_ip: str, dst_ip: str,
                  out_port: int, prio: int):
        dp = self._dp(dpid)
        if dp is None:
            return
        parser  = dp.ofproto_parser
        match   = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ipv4_src=src_ip, ipv4_dst=dst_ip,
        )
        actions = [parser.OFPActionOutput(out_port)]
        self._add_flow(dp, prio, match, actions, idle=FLOW_IDLE, hard=FLOW_HARD)

    def _add_flow(self, dp, priority: int, match, actions,
                  idle: int = 0, hard: int = 0):
        ofproto = dp.ofproto
        parser  = dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod  = parser.OFPFlowMod(
            datapath=dp, priority=priority, match=match,
            instructions=inst,
            idle_timeout=idle, hard_timeout=hard,
            flags=ofproto.OFPFF_SEND_FLOW_REM if idle or hard else 0,
        )
        dp.send_msg(mod)

    def _packet_out(self, dp, msg, in_port):
        ofproto = dp.ofproto
        parser  = dp.ofproto_parser
        data    = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
            actions=[parser.OFPActionOutput(ofproto.OFPP_TABLE)],
            data=data,
        )
        dp.send_msg(out)

    def _flood(self, dp, msg, in_port):
        ofproto = dp.ofproto
        parser  = dp.ofproto_parser
        data    = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
            actions=[parser.OFPActionOutput(ofproto.OFPP_FLOOD)],
            data=data,
        )
        dp.send_msg(out)

    def _write_state_file(self, state: list, loss, avg_util: float, comparison: dict):
        flows = {}
        for (src, dst), entry in self.flow_table.items():
            flows[f"{src}->{dst}"] = {
                "action":   entry.action,
                "path":     ACTION_NAMES.get(entry.action, "?"),
                "age_s":    round(time.time() - entry.start_time, 1),
                "priority": entry.is_priority,
            }
        doc = {
            "t":            time.time(),
            "state":        state,
            "feature_names": FEATURE_NAMES,
            "epsilon":      self.agent.epsilon,
            "learn_steps":  self.learn_steps,
            "total_reward": self.total_reward,
            "last_loss":    loss,
            "path_counts": {
                "PATH_A": self.path_counts.get(0, 0),
                "PATH_B": self.path_counts.get(1, 0),
                "PATH_C": self.path_counts.get(2, 0),
                "DROP":   self.path_counts.get(3, 0),
            },
            "active_flows": flows,
            "avg_util":     avg_util,
            "comparison":   comparison,
        }
        try:
            tmp = RUNTIME_STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(doc, f)
            os.replace(tmp, RUNTIME_STATE_FILE)   # atomic swap
        except OSError:
            pass

    def _dp(self, dpid: int):
        return self.datapaths.get(dpid)

    def close(self):
        """Called by Ryu on shutdown — save final weights and replay buffer."""
        if self.routing_mode == ROUTING_MODE_DQN:
            self.agent.save(WEIGHTS_PATH)
            self.agent.save_buffer(REPLAY_BUFFER_FILE)
        self.logger.info(
            "Shutdown: saved weights+buffer (step=%d, ε=%.4f, buf=%d)",
            self.learn_steps, self.agent.epsilon, len(self.agent.replay),
        )

    # ── Flow removed: clean up tracking table ─────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def flow_removed_handler(self, ev):
        msg = ev.msg
        match = msg.match
        src_ip = match.get("ipv4_src")
        dst_ip = match.get("ipv4_dst")
        if src_ip is None or dst_ip is None:
            return

        flow_key = (src_ip, dst_ip)
        entry = self.flow_table.pop(flow_key, None)
        if entry is None:
            return

        self.path_counts[entry.action] = max(0, self.path_counts.get(entry.action, 0) - 1)

        shadow_entry = self.shadow_flow_table.pop(flow_key, None)
        if shadow_entry is not None:
            shadow_counts = (
                self.baseline_path_counts
                if self.routing_mode == ROUTING_MODE_DQN
                else self.dqn_path_counts
            )
            shadow_counts[shadow_entry.action] = max(
                0, shadow_counts.get(shadow_entry.action, 0) - 1
            )

        # Final experience: mark done=True so agent discounts future correctly
        current_state_seq = list(self.state_buffer)
        reward = compute_reward(entry.state_seq[-1], entry.action, self.prev_state)
        if self.routing_mode == ROUTING_MODE_DQN:
            self.agent.store(entry.state_seq, entry.action, reward, current_state_seq, done=True)
            self.dqn_total_reward += reward
        else:
            self.baseline_total_reward += reward

        if shadow_entry is not None:
            shadow_reward = compute_reward(
                shadow_entry.state_seq[-1], shadow_entry.action, self.prev_state
            )
            if self.routing_mode == ROUTING_MODE_DQN:
                self.baseline_total_reward += shadow_reward
            else:
                self.dqn_total_reward += shadow_reward

        self.logger.debug("Flow removed %s→%s path=%s reward=%.3f",
                          src_ip, dst_ip, ACTION_NAMES[entry.action], reward)

    def _enforce_priority_action(self, action: int, is_priority: bool) -> int:
        # Emergency/actuator flows are never dropped.
        if is_priority and action == ACTION_DROP:
            return ACTION_PATH_A
        return action

    def _named_counts(self, counts: dict[int, int]) -> dict[str, int]:
        return {
            "PATH_A": counts.get(ACTION_PATH_A, 0),
            "PATH_B": counts.get(ACTION_PATH_B, 0),
            "PATH_C": counts.get(ACTION_PATH_C, 0),
            "DROP": counts.get(ACTION_DROP, 0),
        }

    @staticmethod
    def _delta_pct(base: float, compared: float) -> float | None:
        if abs(base) < 1e-9:
            return None
        return ((compared - base) / abs(base)) * 100.0

    def _build_comparison_payload(self) -> dict:
        delta = self.dqn_total_reward - self.baseline_total_reward
        winner = "dqn" if delta > 0 else "baseline" if delta < 0 else "tie"
        return {
            "enabled": self.shadow_compare_enabled,
            "routing_mode": self.routing_mode,
            "baseline_policy": self.baseline_policy,
            "dqn_reward": round(self.dqn_total_reward, 3),
            "baseline_reward": round(self.baseline_total_reward, 3),
            "reward_delta": round(delta, 3),
            "reward_delta_pct": (
                None if (pct := self._delta_pct(self.baseline_total_reward, self.dqn_total_reward)) is None
                else round(pct, 2)
            ),
            "winner": winner,
            "dqn_path_counts": self._named_counts(self.dqn_path_counts),
            "baseline_path_counts": self._named_counts(self.baseline_path_counts),
        }
