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
            return self._rng.choice((ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C))
        return self._least_utilized(state, path_counts or {})

    def _round_robin(self) -> int:
        actions = (ACTION_PATH_A, ACTION_PATH_B, ACTION_PATH_C)
        action = actions[self._rr_counter % len(actions)]
        self._rr_counter += 1
        return action

    def _ecmp_hash(self, flow_key: tuple[str, str], state: list[float]) -> int:
        # Keep flow affinity stable via deterministic hash over src/dst.
        digest = hashlib.sha256(f"{flow_key[0]}->{flow_key[1]}".encode("utf-8")).digest()
        pick = digest[0] % 2
        # Prefer A/B for ECMP; only spill to C if both are highly loaded.
        if self._path_load_b(state) > 0.85 and self._path_load_a(state) > 0.85:
            return ACTION_PATH_C
        return ACTION_PATH_A if pick == 0 else ACTION_PATH_B

    def _least_utilized(self, state: list[float], path_counts: dict[int, int]) -> int:
        load_a = self._path_load_a(state)
        load_b = self._path_load_b(state)
        load_c = self._path_load_c(state)

        # Small active-flow penalty avoids piling onto a single path when loads tie.
        penalty = 0.02
        score_a = load_a + penalty * path_counts.get(ACTION_PATH_A, 0)
        score_b = load_b + penalty * path_counts.get(ACTION_PATH_B, 0)
        score_c = load_c + penalty * path_counts.get(ACTION_PATH_C, 0)

        if score_a <= score_b and score_a <= score_c:
            return ACTION_PATH_A
        if score_b <= score_a and score_b <= score_c:
            return ACTION_PATH_B
        return ACTION_PATH_C

    @staticmethod
    def _path_load_a(state: list[float]) -> float:
        # A uses s1/s2->s3 plus s3->s5.
        return (state[0] + state[2] + state[4]) / 3.0

    @staticmethod
    def _path_load_b(state: list[float]) -> float:
        # B uses s1/s2->s4 plus s4->s5.
        return (state[1] + state[3] + state[5]) / 3.0

    @staticmethod
    def _path_load_c(state: list[float]) -> float:
        # C uses access->s3, crosslink, and s4->s5.
        return (state[0] + state[2] + state[6] + state[5]) / 4.0
