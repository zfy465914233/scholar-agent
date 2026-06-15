---
id: reinforcement-learning-basics
title: Reinforcement Learning Fundamentals
type: knowledge
topic: reinforcement-learning
tags:
  - reinforcement-learning
  - RL
  - markov-decision-process
  - reward
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Reinforcement learning (RL) trains agents to make sequential decisions by maximizing cumulative reward. The agent observes states, takes actions, and is rewarded according to the environment.

## Markov Decision Process

Formalized as MDP = (S, A, P, R, γ):
- S: state space
- A: action space
- P: transition probability
- R: reward function
- γ: discount factor

## Value Functions

V^π(s): expected return starting from state s under policy π
Q^π(s, a): expected return starting from (s, a) under policy π

Q-learning and its deep variant DQN are foundational RL algorithms.
