---
id: adam-optimizer
title: Adam — Adaptive Moment Estimation Optimizer
type: knowledge
topic: optimization
tags:
  - adam
  - optimizer
  - adaptive-learning-rate
  - gradient-descent
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Adam (Adaptive Moment Estimation) is a gradient-descent optimizer that maintains running estimates of the first moment (mean) and second moment (uncentered variance) of gradients, using them to scale per-parameter learning rates.

## Update Rules

m_t = β_1 m_{t-1} + (1-β_1) g_t           (first moment)
v_t = β_2 v_{t-1} + (1-β_2) g_t²           (second moment)
m̂_t = m_t / (1 - β_1^t)                    (bias correction)
θ_t = θ_{t-1} - η · m̂_t / (sqrt(v̂_t) + ε)

## Defaults

β_1 = 0.9, β_2 = 0.999, ε = 1e-8, η = 1e-3. Widely used for training deep neural networks.
