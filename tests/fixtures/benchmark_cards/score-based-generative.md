---
id: score-based-generative
title: Score-Based Generative Models via SDE
type: knowledge
topic: generative-models
tags:
  - score-based
  - generative-model
  - SDE
  - NCSN
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Score-based generative models learn the gradient of the log density (∇ log p(x)) — the "score" — and sample by following Langevin dynamics or solving a stochastic differential equation (SDE).

## Connection to Diffusion

Score-based models unify with diffusion models through a continuous-time SDE. Noise-Conditional Score Networks (NCSN) estimate the score at each noise scale; reverse-time SDE produces samples.

## Sampling

Langevin MCMC sampling uses the score:

x_t = x_{t-1} + (ε/2) ∇ log p(x_{t-1}) + sqrt(ε) z,  z ~ N(0, I)
