import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from collections import deque
import random

class DQN(nn.Module):
    def __init__(self, state_size, action_size):
        super().__init__()
        self.fc = nn.Sequential(
            nn.Linear(state_size, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Linear(128, action_size)
        )
    
    def forward(self, x):
        return self.fc(x)

class DQNAgent:
    def __init__(self, state_size=7, action_size=3):
        self.state_size = state_size
        self.action_size = action_size
        self.memory = deque(maxlen=50000)
        self.gamma = 0.99
        self.epsilon = 1.0
        self.epsilon_min = 0.05
        self.epsilon_decay = 0.995
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        self.model = DQN(state_size, action_size).to(self.device)
        self.target_model = DQN(state_size, action_size).to(self.device)
        self.target_model.load_state_dict(self.model.state_dict())
        self.optimizer = optim.Adam(self.model.parameters(), lr=0.0005)
        self.update_counter = 0
        self.target_update_freq = 250
        self.last_loss = 0
    
    def act(self, state):
        if np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)
        state = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        with torch.no_grad():
            q_values = self.model(state)
        return q_values.argmax().item()
    
    def remember(self, state, action, reward, next_state, done):
        self.memory.append((state, action, reward, next_state, done))
    
    def replay(self, batch_size=128):
        if len(self.memory) < batch_size:
            return 0
        
        batch = random.sample(self.memory, batch_size)
        states = torch.FloatTensor(np.array([x[0] for x in batch])).to(self.device)
        actions = torch.LongTensor([x[1] for x in batch]).to(self.device)
        rewards = torch.FloatTensor([x[2] for x in batch]).to(self.device)
        next_states = torch.FloatTensor(np.array([x[3] for x in batch])).to(self.device)
        dones = torch.FloatTensor([x[4] for x in batch]).to(self.device)
        
        current_q = self.model(states).gather(1, actions.unsqueeze(1)).squeeze(1)

        # Double DQN: online model selects the action, target model evaluates it.
        next_actions = self.model(next_states).argmax(1, keepdim=True)
        next_q = self.target_model(next_states).gather(1, next_actions).squeeze(1).detach()
        target_q = rewards + (1 - dones) * self.gamma * next_q
        
        loss = nn.SmoothL1Loss()(current_q, target_q)
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
        self.optimizer.step()
        
        self.last_loss = loss.item()
        
        # Update target network
        self.update_counter += 1
        if self.update_counter % self.target_update_freq == 0:
            self.target_model.load_state_dict(self.model.state_dict())
        
        return self.last_loss

    def end_episode(self):
        if self.epsilon > self.epsilon_min:
            self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
    
    def save(self, path):
        torch.save({
            "model": self.model.state_dict(),
            "target_model": self.target_model.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "epsilon": self.epsilon,
            "state_size": self.state_size,
            "action_size": self.action_size,
        }, path)
    
    def load(self, path):
        checkpoint = torch.load(path, map_location=self.device)
        try:
            if isinstance(checkpoint, dict) and "model" in checkpoint:
                self.model.load_state_dict(checkpoint["model"])
                self.target_model.load_state_dict(checkpoint.get("target_model", checkpoint["model"]))
                if "optimizer" in checkpoint:
                    self.optimizer.load_state_dict(checkpoint["optimizer"])
                self.epsilon = checkpoint.get("epsilon", self.epsilon)
            else:
                self.model.load_state_dict(checkpoint)
                self.target_model.load_state_dict(self.model.state_dict())
            return True
        except RuntimeError:
            return False
