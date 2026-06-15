---
id: ppo-policy-gradient
title: Proximal Policy Optimization (PPO)
type: knowledge
topic: reinforcement-learning
tags:
  - PPO
  - policy-gradient
  - RL
  - RLHF
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Proximal Policy Optimization (PPO) is a policy-gradient method for reinforcement learning that limits the update size at each step, preventing the new policy from straying too far from the old one.

## Clipped Objective

L^CLIP(θ) = E[min(r_t(θ) A_t, clip(r_t(θ), 1-ε, 1+ε) A_t)]

where r_t(θ) = π_θ(a|s) / π_θ_old(a|s) is the probability ratio.

## Applications

PPO is the de-facto standard for RLHF (Reinforcement Learning from Human Feedback) used to align large language models.
