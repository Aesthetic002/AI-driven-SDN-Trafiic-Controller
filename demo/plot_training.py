import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


def read_monitor(path):
    rewards = []
    lengths = []
    with open(path, newline="") as handle:
        for row in csv.DictReader(line for line in handle if not line.startswith("#")):
            rewards.append(float(row["r"]))
            lengths.append(int(row["l"]))
    return rewards, lengths


def rolling_average(values, window):
    if not values:
        return []

    averages = []
    for index in range(len(values)):
        start = max(0, index - window + 1)
        chunk = values[start : index + 1]
        averages.append(sum(chunk) / len(chunk))
    return averages


def plot_monitor(path, window=50, output="runs/sb3/training_plot.png"):
    rewards, lengths = read_monitor(path)
    episodes = range(1, len(rewards) + 1)
    reward_avg = rolling_average(rewards, window)
    length_avg = rolling_average(lengths, window)

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(episodes, rewards, color="#9fb3c8", alpha=0.35, label="episode reward")
    axes[0].plot(episodes, reward_avg, color="#29be9e", label=f"{window}-episode average")
    axes[0].set_ylabel("Reward")
    axes[0].legend()

    axes[1].plot(episodes, lengths, color="#9fb3c8", alpha=0.35, label="episode length")
    axes[1].plot(episodes, length_avg, color="#ffba49", label=f"{window}-episode average")
    axes[1].set_xlabel("Episode")
    axes[1].set_ylabel("Steps")
    axes[1].legend()

    fig.tight_layout()
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    print(f"Saved plot to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot SB3 monitor training logs.")
    parser.add_argument("--monitor", default="runs/sb3/monitor.csv")
    parser.add_argument("--window", type=int, default=50)
    parser.add_argument("--output", default="runs/sb3/training_plot.png")
    args = parser.parse_args()
    plot_monitor(args.monitor, args.window, args.output)
