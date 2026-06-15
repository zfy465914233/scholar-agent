---
id: stochastic-gradient-descent
title: Stochastic Gradient Descent (SGD)
type: knowledge
topic: optimization
tags:
  - SGD
  - gradient-descent
  - optimization
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Stochastic Gradient Descent updates parameters using the gradient estimated from a mini-batch of samples, rather than the full dataset. This trades exactness for scalability.

## Update Rule

θ_{t+1} = θ_t - η · ∇L(θ_t; B_t),  B_t ~ Dataset

## Variants

- Mini-batch SGD: B_t has 32-512 samples
- Momentum: v_t = μ v_{t-1} + η ∇L; θ_t -= v_t
- Nesterov momentum: lookahead variant with better convergence guarantees

SGD with momentum often generalizes better than adaptive methods like Adam on convex problems.
