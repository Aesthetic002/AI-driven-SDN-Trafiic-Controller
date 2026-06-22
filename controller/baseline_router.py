"""
Baseline routing policies used for A/B comparison and baseline-only demos.
"""

from __future__ import annotations

import hashlib
import random

from constants import (
    ACTION_PATH_A,
    ACTION_PATH_B,
    ACTION_PATH_C,
    ACTION_PATH_D,
    ACTION_PATH_E,
)

BASELINE_SHORTEST_PATH = "shortest_path"
BASELINE_ECMP_HASH = "ecmp_hash"
BASELINE_ROUND_ROBIN = "round_robin"
BASELINE_LEAST_UTILIZED = "least_utilized"
BASELINE_RANDOM = "random"

BASELINE_POLICIES = {
    BASELINE_SHORTEST_PATH,
    BASELINE_ECMP_HASH,
    BASELINE_ROUND_ROBIN,
    BASELINE_LEAST_UTILIZED,
    BASELINE_RANDOM,
}


class BaselineRouter:
    def __init__(self, policy: str = BASELINE_LEAST_UTILIZED, seed: int = 42):
        self.policy = policy if policy in BASELINE_POLICIES else BASELINE_LEAST_UTILIZED
        self._rr_counter = 0
        self._rng = random.Random(seed)

    def select_action(
        self,
        flow_key: tuple[str, str],
        state: list[float],
        path_counts: dict[int, int] | None = None,
    ) -> int:
        if self.policy == BASELINE_SHORTEST_PATH:
            return ACTION_PATH_A
        if self.policy == BASELINE_ECMP_HASH:
            return self._ecmp_hash(flow_key, state)
        if self.policy == BASELINE_ROUND_ROBIN:
            return self._round_robin()
        if self.policy == BASELINE_RANDOM:
            return self._rng.choice((ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C,
                                     ACTION_PATH_D, ACTION_PATH_E))
        return self._least_utilized(state, path_counts or {})

    def _round_robin(self) -> int:
        actions = (ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C,
                   ACTION_PATH_D, ACTION_PATH_E)
        action = actions[self._rr_counter % len(actions)]
        self._rr_counter += 1
        return action

    def _ecmp_hash(self, flow_key: tuple[str, str], state: list[float]) -> int:
        # Keep flow affinity stable via deterministic hash over src/dst.
        digest = hashlib.sha256(f"{flow_key[0]}->{flow_key[1]}".encode("utf-8")).digest()
        pick = digest[0] % 4   # 0-3 → A, B, D, E
        load_a = self._path_load_a(state)
        load_b = self._path_load_b(state)
        # Spill to secondary paths only if both primary paths are heavily loaded
        if load_a > 0.85 and load_b > 0.85:
            return ACTION_PATH_C
        path_map = {0: ACTION_PATH_A, 1: ACTION_PATH_B,
                    2: ACTION_PATH_D, 3: ACTION_PATH_E}
        return path_map[pick]

    def _least_utilized(self, state: list[float], path_counts: dict[int, int]) -> int:
        load_a = self._path_load_a(state)
        load_b = self._path_load_b(state)
        load_c = self._path_load_c(state)
        load_d = self._path_load_d(state)
        load_e = self._path_load_e(state)

        # Small active-flow penalty avoids piling onto a single path when loads tie.
        penalty = 0.02
        scores = {
            ACTION_PATH_A: load_a + penalty * path_counts.get(ACTION_PATH_A, 0),
            ACTION_PATH_B: load_b + penalty * path_counts.get(ACTION_PATH_B, 0),
            ACTION_PATH_C: load_c + penalty * path_counts.get(ACTION_PATH_C, 0),
            ACTION_PATH_D: load_d + penalty * path_counts.get(ACTION_PATH_D, 0),
            ACTION_PATH_E: load_e + penalty * path_counts.get(ACTION_PATH_E, 0),
        }
        return min(scores, key=scores.__getitem__)

    @staticmethod
    def _path_load_a(state: list[float]) -> float:
        return (state[0] + state[2] + state[4]) / 3.0

    @staticmethod
    def _path_load_b(state: list[float]) -> float:
        return (state[1] + state[3] + state[5]) / 3.0

    @staticmethod
    def _path_load_c(state: list[float]) -> float:
        return (state[0] + state[2] + state[6] + state[5]) / 4.0

    @staticmethod
    def _path_load_d(state: list[float]) -> float:
        # D uses s1/s2/s6->s3 plus s3->s7 (index 22 if present)
        s3_s7 = state[22] if len(state) > 22 else 0.0
        return (state[0] + state[2] + s3_s7) / 3.0

    @staticmethod
    def _path_load_e(state: list[float]) -> float:
        # E uses s1/s2/s6->s4 plus s4->s7 (index 23 if present)
        s4_s7 = state[23] if len(state) > 23 else 0.0
        return (state[1] + state[3] + s4_s7) / 3.0
