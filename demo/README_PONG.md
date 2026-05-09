# DQN Pong - Self-Learning AI

A minimal implementation of Deep Q-Network (DQN) agents learning to play Pong through self-play.

## Setup with uv

```bash
# Create virtual environment with Python 3.11 (stable)
uv venv --python 3.11

# Activate virtual environment
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate    # Windows

# Install dependencies
uv pip install -r requirements.txt
```

## Run Training

Custom two-agent self-play:

```bash
python train_pong.py
```

Stable-Baselines3 single-agent baseline:

```bash
python train_sb3.py --timesteps 100000
```

Evaluate trained agents:

```bash
python evaluate.py --mode custom --episodes 20
python evaluate.py --mode sb3 --episodes 20
```

Plot SB3 monitor logs:

```bash
python plot_training.py
```

## How It Works

- **Two DQN agents** play against each other, learning simultaneously
- **State**: Player-relative ball position/velocity, own/opponent paddle positions, and ball-to-paddle offset (7 features)
- **Actions**: Stay, move up, move down
- **Rewards**: hit/rally rewards, score rewards, miss penalties, and small shaping rewards for tracking the incoming ball
- **Learning**: Double DQN targets, Huber loss, gradient clipping, target network updates, and episode-level epsilon decay
- **Models auto-save** every 100 episodes to `agent1.pth` and `agent2.pth`
- Training runs for 5000 episodes with live visualization

## Baseline Comparison

`gym_pong_env.py` exposes a Gymnasium-compatible single-agent environment. It trains the left paddle against a simple tracking opponent, which is useful for checking whether the custom DQN is weak or the environment/reward design is weak.

`train_sb3.py` trains Stable-Baselines3 DQN and logs to:

- `models/`
- `runs/sb3/`

## UI Controls

- `Space`: Pause or resume
- `S`: Save both agents immediately
- `R`: Reset displayed score and rolling metrics
- `+` / `-`: Increase or decrease simulation speed
- Drag the bottom-right slider to change FPS

## Model Persistence

Models are automatically saved and loaded. To start fresh, delete `agent1.pth` and `agent2.pth`.

Older checkpoints trained with the previous 6-feature state cannot be loaded into the current 7-feature network; they are skipped automatically and replaced the next time the program saves.

## Collision Fix

The environment now checks paddle collisions using the ball radius and whether the ball crossed the paddle plane during the frame. This avoids false losses where the ball visually overlaps the paddle but the old center-only check counted it as a miss.
