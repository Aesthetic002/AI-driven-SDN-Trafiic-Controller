from pathlib import Path
import argparse

from stable_baselines3 import DQN
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.callbacks import CheckpointCallback

from gym_pong_env import SingleAgentPongEnv


def train(total_timesteps=100_000):
    output_dir = Path("models")
    run_dir = Path("runs/sb3")
    output_dir.mkdir(exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    env = Monitor(SingleAgentPongEnv(opponent="tracking"), filename=str(run_dir / "monitor.csv"))
    checkpoint_callback = CheckpointCallback(
        save_freq=10_000,
        save_path=str(output_dir),
        name_prefix="sb3_dqn_pong",
    )

    model = DQN(
        "MlpPolicy",
        env,
        learning_rate=5e-4,
        buffer_size=50_000,
        learning_starts=1_000,
        batch_size=128,
        gamma=0.99,
        train_freq=4,
        target_update_interval=500,
        exploration_fraction=0.35,
        exploration_final_eps=0.05,
        tensorboard_log=str(run_dir),
        verbose=1,
    )
    model.learn(total_timesteps=total_timesteps, callback=checkpoint_callback)
    model.save(output_dir / "sb3_dqn_pong_final")
    env.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train a Stable-Baselines3 DQN Pong baseline.")
    parser.add_argument("--timesteps", type=int, default=100_000)
    args = parser.parse_args()
    train(total_timesteps=args.timesteps)
