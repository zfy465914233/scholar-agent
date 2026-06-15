---
id: multi-armed-bandit
title: Multi-Armed Bandit — Exploration vs Exploitation
type: knowledge
topic: reinforcement-learning
tags:
  - bandit
  - exploration
  - reinforcement-learning
  - RL
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

A multi-armed bandit is the simplest reinforcement learning setting: an agent chooses one of K arms each round and observes a stochastic reward. The challenge is balancing exploration (trying new arms) and exploitation (choosing the best-known arm).

## Algorithms

- ε-greedy: explore with probability ε, otherwise exploit
- UCB (Upper Confidence Bound): pick arm maximizing μ̂_a + sqrt(2 ln t / n_a)
- Thompson sampling: sample from posterior, pick argmax

## Regret Bounds

UCB and Thompson sampling achieve O(sqrt(K T ln T)) cumulative regret, optimal up to constants.

Bandits are RL with state size 1; full RL generalizes to sequential decisions.
