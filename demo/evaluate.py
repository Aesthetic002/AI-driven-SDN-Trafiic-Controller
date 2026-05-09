import argparse
import os

import pygame

from dqn_agent import DQNAgent
from gym_pong_env import SingleAgentPongEnv
from pong_env import PongEnv


def evaluate_custom(agent1_path="agent1.pth", agent2_path="agent2.pth", episodes=20, render=True):
    pygame.init()
    env = PongEnv()
    screen = pygame.display.set_mode((env.width, env.height))
    clock = pygame.time.Clock()

    agent1 = DQNAgent()
    agent2 = DQNAgent()
    if os.path.exists(agent1_path):
        agent1.load(agent1_path)
    if os.path.exists(agent2_path):
        agent2.load(agent2_path)
    agent1.epsilon = 0.0
    agent2.epsilon = 0.0

    scores = {1: 0, 2: 0}
    rallies = []

    for _ in range(episodes):
        state1, state2 = env.reset()
        for _ in range(1000):
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    return scores, rallies

            action1 = agent1.act(state1)
            action2 = agent2.act(state2)
            state1, state2, _, _, done = env.step(action1, action2)

            if render:
                env.render(screen, panel_height=0)
                pygame.display.flip()
                clock.tick(60)

            if done:
                scores[env.last_winner] += 1
                rallies.append(env.rally_count)
                break

    pygame.quit()
    return scores, rallies


def evaluate_sb3(model_path="models/sb3_dqn_pong_final.zip", episodes=20, render=True):
    from stable_baselines3 import DQN

    env = SingleAgentPongEnv(render_mode="human" if render else None)
    model = DQN.load(model_path)
    wins = 0
    rallies = []

    for _ in range(episodes):
        obs, _ = env.reset()
        done = False
        truncated = False
        while not done and not truncated:
            action, _ = model.predict(obs, deterministic=True)
            obs, _, done, truncated, info = env.step(action)
            if render:
                env.render()
        wins += int(info["winner"] == 1)
        rallies.append(info["rally"])

    env.close()
    return {"agent_wins": wins, "episodes": episodes}, rallies


def print_summary(scores, rallies):
    avg_rally = sum(rallies) / len(rallies) if rallies else 0
    print(f"Scores: {scores}")
    print(f"Average rally: {avg_rally:.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate trained Pong agents.")
    parser.add_argument("--mode", choices=["custom", "sb3"], default="custom")
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--model", default="models/sb3_dqn_pong_final.zip")
    args = parser.parse_args()

    if args.mode == "sb3":
        scores, rallies = evaluate_sb3(args.model, args.episodes, not args.no_render)
    else:
        scores, rallies = evaluate_custom(episodes=args.episodes, render=not args.no_render)
    print_summary(scores, rallies)
