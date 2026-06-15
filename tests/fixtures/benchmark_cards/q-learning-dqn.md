---
id: q-learning-dqn
title: Q-Learning and Deep Q-Networks
type: knowledge
topic: reinforcement-learning
tags:
  - q-learning
  - DQN
  - value-based
  - RL
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Q-learning is a value-based RL algorithm that learns the optimal action-value function Q*(s, a) via temporal difference updates. DQN (Deep Q-Network) extends this with deep neural networks.

## Update Rule

Q(s, a) ← Q(s, a) + α [r + γ max_a' Q(s', a') - Q(s, a)]

## DQN Innovations

- Experience replay: randomize samples to break correlation
- Target network: stabilize training by fixing Q-targets periodically

DQN achieved human-level performance on Atari games from raw pixels.
