import numpy as np
import gymnasium as gym
from gymnasium import spaces

from pong_env import PongEnv


class SingleAgentPongEnv(gym.Env):
    """Gymnasium wrapper for benchmarking one DQN agent against a simple opponent."""

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 60}

    def __init__(self, render_mode=None, max_episode_steps=1000, opponent="tracking"):
        super().__init__()
        self.base_env = PongEnv()
        self.render_mode = render_mode
        self.max_episode_steps = max_episode_steps
        self.opponent = opponent
        self.steps = 0
        self.screen = None
        self.clock = None

        self.action_space = spaces.Discrete(3)
        self.observation_space = spaces.Box(low=-1.5, high=1.5, shape=(7,), dtype=np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            np.random.seed(seed)

        state1, _ = self.base_env.reset()
        self.steps = 0
        return state1, self._info()

    def step(self, action):
        self.steps += 1
        opponent_action = self._opponent_action()
        state1, _, reward1, _, done = self.base_env.step(int(action), opponent_action)

        truncated = self.steps >= self.max_episode_steps
        if truncated and not done:
            reward1 += 1.0

        return state1, float(reward1), bool(done), bool(truncated), self._info()

    def render(self):
        if self.render_mode is None:
            return None

        import pygame

        if self.screen is None:
            pygame.init()
            self.screen = pygame.display.set_mode((self.base_env.width, self.base_env.height))
            pygame.display.set_caption("Single-Agent Gym Pong")
            self.clock = pygame.time.Clock()

        self.base_env.render(self.screen, panel_height=0)
        pygame.display.flip()
        self.clock.tick(self.metadata["render_fps"])

        if self.render_mode == "rgb_array":
            return np.transpose(pygame.surfarray.array3d(self.screen), (1, 0, 2))
        return None

    def close(self):
        if self.screen is not None:
            import pygame

            pygame.quit()
            self.screen = None
            self.clock = None

    def _opponent_action(self):
        if self.opponent == "random":
            return self.action_space.sample()

        ball_y = self.base_env.ball_y
        paddle_center = self.base_env.paddle2_y + self.base_env.paddle_height / 2
        dead_zone = self.base_env.paddle_speed * 0.75
        if ball_y < paddle_center - dead_zone:
            return 1
        if ball_y > paddle_center + dead_zone:
            return 2
        return 0

    def _info(self):
        return {
            "rally": self.base_env.rally_count,
            "winner": self.base_env.last_winner,
            "steps": self.steps,
        }
