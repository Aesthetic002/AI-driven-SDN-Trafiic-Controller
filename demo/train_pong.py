import pygame
import os
from collections import deque
from pong_env import PongEnv
from dqn_agent import DQNAgent

WIDTH = 600
HEIGHT = 540
PLAY_HEIGHT = 400
PANEL_HEIGHT = HEIGHT - PLAY_HEIGHT

def draw_text(screen, font, text, x, y, color=(220, 228, 240)):
    screen.blit(font.render(text, True, color), (x, y))

def draw_metric(screen, font, label, value, x, y, color):
    pygame.draw.rect(screen, (26, 34, 48), (x, y, 132, 40), border_radius=8)
    draw_text(screen, font, label, x + 10, y + 6, (133, 146, 166))
    draw_text(screen, font, value, x + 10, y + 21, color)

def train():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.SCALED)
    pygame.display.set_caption("DQN Pong - Self Play Lab")
    clock = pygame.time.Clock()
    title_font = pygame.font.Font(None, 34)
    small_font = pygame.font.Font(None, 24)
    tiny_font = pygame.font.Font(None, 20)
    
    env = PongEnv()
    agent1 = DQNAgent()
    agent2 = DQNAgent()
    
    # Load existing models if available
    if os.path.exists("agent1.pth"):
        if agent1.load("agent1.pth"):
            print("Loaded agent1 model")
        else:
            print("Skipped agent1.pth because it does not match the current network")
    if os.path.exists("agent2.pth"):
        if agent2.load("agent2.pth"):
            print("Loaded agent2 model")
        else:
            print("Skipped agent2.pth because it does not match the current network")
    
    episodes = 5000
    save_interval = 100
    score1 = 0
    score2 = 0
    speed = 60  # FPS
    slider_x = 450
    slider_dragging = False
    paused = False
    running = True
    recent_rallies = deque(maxlen=50)
    recent_rewards1 = deque(maxlen=50)
    recent_rewards2 = deque(maxlen=50)
    action_names = ("stay", "up", "down")
    
    episode = 0
    while episode < episodes and running:
        state1, state2 = env.reset()
        total_reward1 = 0
        total_reward2 = 0
        last_action1 = 0
        last_action2 = 0
        
        for step in range(1000):
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    mx, my = event.pos
                    if 428 <= my <= 448 and 398 <= mx <= 552:
                        slider_dragging = True
                elif event.type == pygame.MOUSEBUTTONUP:
                    slider_dragging = False
                elif event.type == pygame.MOUSEMOTION and slider_dragging:
                    mx = event.pos[0]
                    slider_x = max(400, min(550, mx))
                    speed = int((slider_x - 400) / 150 * 290 + 10)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        paused = not paused
                    elif event.key == pygame.K_r:
                        score1 = 0
                        score2 = 0
                        recent_rallies.clear()
                        recent_rewards1.clear()
                        recent_rewards2.clear()
                    elif event.key == pygame.K_s:
                        agent1.save("agent1.pth")
                        agent2.save("agent2.pth")
                        print("Models saved manually")
                    elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                        speed = min(300, speed + 10)
                        slider_x = 400 + (speed - 10) / 290 * 150
                    elif event.key == pygame.K_MINUS:
                        speed = max(10, speed - 10)
                        slider_x = 400 + (speed - 10) / 290 * 150

            if not running:
                break

            if paused:
                env.render(screen, panel_height=PANEL_HEIGHT)
                draw_text(screen, title_font, "Paused", 252, 178, (238, 245, 255))
                draw_text(screen, small_font, "Space resumes | S saves | R resets stats", 154, 212, (180, 190, 205))
                pygame.display.flip()
                clock.tick(30)
                continue
            
            action1 = agent1.act(state1)
            action2 = agent2.act(state2)
            last_action1 = action1
            last_action2 = action2
            
            next_state1, next_state2, reward1, reward2, done = env.step(action1, action2)
            
            if done:
                if reward1 == 10:
                    score1 += 1
                if reward2 == 10:
                    score2 += 1
            
            agent1.remember(state1, action1, reward1, next_state1, done)
            agent2.remember(state2, action2, reward2, next_state2, done)
            
            agent1.replay()
            agent2.replay()
            
            total_reward1 += reward1
            total_reward2 += reward2
            state1 = next_state1
            state2 = next_state2
            
            # Render game
            env.render(screen, panel_height=PANEL_HEIGHT)
            
            draw_text(screen, title_font, str(score1), 245, 24, (41, 190, 158))
            draw_text(screen, title_font, str(score2), 337, 24, (255, 186, 73))
            draw_text(screen, tiny_font, f"rally {env.rally_count}", 276, 58, (145, 156, 173))
            draw_text(screen, small_font, "DQN Pong Self-Play Lab", 14, 412, (238, 245, 255))
            draw_text(screen, tiny_font, "Space pause | S save | R reset stats | +/- speed", 14, 438, (145, 156, 173))

            avg_rally = sum(recent_rallies) / len(recent_rallies) if recent_rallies else 0
            avg_reward1 = sum(recent_rewards1) / len(recent_rewards1) if recent_rewards1 else 0
            avg_reward2 = sum(recent_rewards2) / len(recent_rewards2) if recent_rewards2 else 0
            draw_metric(screen, tiny_font, "Episode", str(episode), 14, 468, (238, 245, 255))
            draw_metric(screen, tiny_font, "A1 ε/loss", f"{agent1.epsilon:.2f}/{agent1.last_loss:.3f}", 154, 468, (41, 190, 158))
            draw_metric(screen, tiny_font, "A2 ε/loss", f"{agent2.epsilon:.2f}/{agent2.last_loss:.3f}", 294, 468, (255, 186, 73))
            draw_metric(screen, tiny_font, "Avg rally", f"{avg_rally:.1f}", 434, 468, (180, 190, 205))
            draw_text(screen, tiny_font, f"A1 {action_names[last_action1]} | A2 {action_names[last_action2]} | R {avg_reward1:.1f}/{avg_reward2:.1f}", 14, 514, (145, 156, 173))
            
            # Draw speed slider
            pygame.draw.rect(screen, (64, 76, 96), (400, 428, 150, 8), border_radius=4)
            pygame.draw.rect(screen, (90, 164, 255), (400, 428, slider_x - 400, 8), border_radius=4)
            pygame.draw.circle(screen, (238, 245, 255), (int(slider_x), 432), 8)
            draw_text(screen, tiny_font, f"{speed} FPS", 452, 442, (180, 190, 205))
            
            pygame.display.flip()
            clock.tick(speed)
            
            if done:
                recent_rallies.append(env.rally_count)
                recent_rewards1.append(total_reward1)
                recent_rewards2.append(total_reward2)
                break
        
        if not running:
            break

        agent1.end_episode()
        agent2.end_episode()

        if episode % 10 == 0:
            print(f"Episode {episode}, Agent1: {total_reward1:.1f}, Agent2: {total_reward2:.1f}, Epsilon: {agent1.epsilon:.3f}")
        
        if episode % save_interval == 0 and episode > 0:
            agent1.save("agent1.pth")
            agent2.save("agent2.pth")
            print(f"Models saved at episode {episode}")

        episode += 1
    
    agent1.save("agent1.pth")
    agent2.save("agent2.pth")
    pygame.quit()
    print("Training complete!")

if __name__ == "__main__":
    train()
