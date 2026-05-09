import pygame
import numpy as np

class PongEnv:
    def __init__(self, width=600, height=400):
        self.width = width
        self.height = height
        self.paddle_width = 10
        self.paddle_height = 72
        self.paddle_margin = 12
        self.ball_size = 10
        self.paddle_speed = 6
        self.ball_speed_x = 3.0
        self.max_ball_speed_x = 6.0
        self.max_ball_speed_y = 4.0
        self.ball_speed_growth = 1.005
        self.last_winner = None
        self.rally_count = 0
        self.prev_action1 = 0
        self.prev_action2 = 0
        self.prev_paddle1_y = 0
        self.prev_paddle2_y = 0
        self.reset()
    
    def reset(self):
        self.ball_x = self.width // 2
        self.ball_y = self.height // 2
        self.ball_vx = np.random.choice([-self.ball_speed_x, self.ball_speed_x])
        self.ball_vy = np.random.uniform(-2, 2)
        self.paddle1_y = self.height // 2 - self.paddle_height // 2
        self.paddle2_y = self.height // 2 - self.paddle_height // 2
        self.rally_count = 0
        self.last_winner = None
        self.prev_action1 = 0
        self.prev_action2 = 0
        self.prev_paddle1_y = self.paddle1_y
        self.prev_paddle2_y = self.paddle2_y
        return self.get_state(1), self.get_state(2)
    
    def get_state(self, player=1):
        if player == 1:
            ball_x = self.ball_x / self.width
            ball_vx = self.ball_vx / self.ball_speed_x
            own_paddle_y = self.paddle1_y / (self.height - self.paddle_height)
            opponent_paddle_y = self.paddle2_y / (self.height - self.paddle_height)
        else:
            ball_x = (self.width - self.ball_x) / self.width
            ball_vx = -self.ball_vx / self.ball_speed_x
            own_paddle_y = self.paddle2_y / (self.height - self.paddle_height)
            opponent_paddle_y = self.paddle1_y / (self.height - self.paddle_height)

        # Player-relative observations let both agents solve the same control problem.
        return np.array([
            ball_x,
            self.ball_y / self.height,
            ball_vx,
            self.ball_vy / self.max_ball_speed_y,
            own_paddle_y,
            opponent_paddle_y,
            (self.ball_y - (own_paddle_y * (self.height - self.paddle_height) + self.paddle_height / 2)) / self.height,
        ], dtype=np.float32)
    
    def step(self, action1, action2):
        prev_ball_x = self.ball_x
        prev_ball_y = self.ball_y

        # Actions: 0=stay, 1=up, 2=down
        if action1 == 1:
            self.paddle1_y = max(0, self.paddle1_y - self.paddle_speed)
        elif action1 == 2:
            self.paddle1_y = min(self.height - self.paddle_height, self.paddle1_y + self.paddle_speed)
        
        if action2 == 1:
            self.paddle2_y = max(0, self.paddle2_y - self.paddle_speed)
        elif action2 == 2:
            self.paddle2_y = min(self.height - self.paddle_height, self.paddle2_y + self.paddle_speed)
        
        self.ball_x += self.ball_vx
        self.ball_y += self.ball_vy
        
        # Ball collision with top/bottom
        radius = self.ball_size / 2
        if self.ball_y <= radius:
            self.ball_y = radius
            self.ball_vy *= -1
        elif self.ball_y >= self.height - radius:
            self.ball_y = self.height - radius
            self.ball_vy *= -1
        
        reward1, reward2 = 0, 0
        done = False
        
        # Smooth movement reward: penalize action changes
        action_change_penalty1 = -0.05 if action1 != self.prev_action1 and self.prev_action1 != 0 else 0
        action_change_penalty2 = -0.05 if action2 != self.prev_action2 and self.prev_action2 != 0 else 0
        reward1 += action_change_penalty1
        reward2 += action_change_penalty2
        
        paddle1_center = self.paddle1_y + self.paddle_height / 2
        paddle2_center = self.paddle2_y + self.paddle_height / 2
        
        # Shape rewards only when the ball is approaching that paddle.
        if self.ball_vx < 0:
            if (self.ball_y > paddle1_center and action1 == 2) or (self.ball_y < paddle1_center and action1 == 1):
                reward1 += 0.03
        if self.ball_vx > 0:
            if (self.ball_y > paddle2_center and action2 == 2) or (self.ball_y < paddle2_center and action2 == 1):
                reward2 += 0.03
        
        dist1 = abs(paddle1_center - self.ball_y) / self.height
        dist2 = abs(paddle2_center - self.ball_y) / self.height
        if self.ball_vx < 0:
            reward1 -= dist1 * 0.02
        if self.ball_vx > 0:
            reward2 -= dist2 * 0.02
        
        # Ball collision with paddles
        left_paddle_x = self.paddle_margin + self.paddle_width
        right_paddle_x = self.width - self.paddle_margin - self.paddle_width

        prev_left_edge = prev_ball_x - radius
        curr_left_edge = self.ball_x - radius
        prev_right_edge = prev_ball_x + radius
        curr_right_edge = self.ball_x + radius
        crossed_left_paddle = prev_left_edge >= left_paddle_x and curr_left_edge <= left_paddle_x
        crossed_right_paddle = prev_right_edge <= right_paddle_x and curr_right_edge >= right_paddle_x

        left_collision_y = self._collision_y_at_x(prev_left_edge, curr_left_edge, left_paddle_x, prev_ball_y)
        right_collision_y = self._collision_y_at_x(prev_right_edge, curr_right_edge, right_paddle_x, prev_ball_y)
        left_y_overlap = self.paddle1_y - radius <= left_collision_y <= self.paddle1_y + self.paddle_height + radius
        right_y_overlap = self.paddle2_y - radius <= right_collision_y <= self.paddle2_y + self.paddle_height + radius

        if crossed_left_paddle:
            if left_y_overlap:
                self.ball_vx = min(abs(self.ball_vx) * self.ball_speed_growth, self.max_ball_speed_x)
                self.ball_x = left_paddle_x + radius
                self.ball_y = left_collision_y
                hit_offset = (left_collision_y - paddle1_center) / (self.paddle_height / 2)
                self.ball_vy = np.clip(hit_offset * self.max_ball_speed_y, -self.max_ball_speed_y, self.max_ball_speed_y)
                self.rally_count += 1
                reward1 += 1 + min(self.rally_count, 20) * 0.05
            else:
                reward1 = -10
                reward2 = 10
                self.last_winner = 2
                done = True
        
        if crossed_right_paddle:
            if right_y_overlap:
                self.ball_vx = -min(abs(self.ball_vx) * self.ball_speed_growth, self.max_ball_speed_x)
                self.ball_x = right_paddle_x - radius
                self.ball_y = right_collision_y
                hit_offset = (right_collision_y - paddle2_center) / (self.paddle_height / 2)
                self.ball_vy = np.clip(hit_offset * self.max_ball_speed_y, -self.max_ball_speed_y, self.max_ball_speed_y)
                self.rally_count += 1
                reward2 += 1 + min(self.rally_count, 20) * 0.05
            else:
                reward2 = -10
                reward1 = 10
                self.last_winner = 1
                done = True
        
        # Update previous actions
        self.prev_action1 = action1
        self.prev_action2 = action2
        
        return self.get_state(1), self.get_state(2), reward1, reward2, done

    def _collision_y_at_x(self, prev_edge_x, curr_edge_x, collision_x, prev_ball_y):
        travel_x = curr_edge_x - prev_edge_x
        if travel_x == 0:
            return self.ball_y
        t = np.clip((collision_x - prev_edge_x) / travel_x, 0.0, 1.0)
        return prev_ball_y + (self.ball_y - prev_ball_y) * t
    
    def render(self, screen, panel_height=120):
        play_rect = pygame.Rect(0, 0, self.width, self.height)
        pygame.draw.rect(screen, (9, 12, 18), play_rect)

        for y in range(10, self.height, 26):
            pygame.draw.line(screen, (49, 61, 79), (self.width // 2, y), (self.width // 2, y + 12), 2)

        pygame.draw.rect(screen, (41, 190, 158), (self.paddle_margin, int(self.paddle1_y), self.paddle_width, self.paddle_height), border_radius=4)
        pygame.draw.rect(
            screen,
            (255, 186, 73),
            (self.width - self.paddle_width - self.paddle_margin, int(self.paddle2_y), self.paddle_width, self.paddle_height),
            border_radius=4,
        )
        pygame.draw.circle(screen, (238, 245, 255), (int(self.ball_x), int(self.ball_y)), self.ball_size // 2)
        pygame.draw.rect(screen, (18, 24, 34), (0, self.height, self.width, panel_height))
