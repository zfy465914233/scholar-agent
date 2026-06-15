---
id: batch-normalization
title: Batch Normalization for Deep Networks
type: knowledge
topic: optimization
tags:
  - batch-normalization
  - BatchNorm
  - normalization
  - training-stability
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Batch Normalization (BatchNorm) normalizes layer inputs using the mean and variance computed over the current mini-batch, then applies a learned scale γ and shift β.

## Formula

μ_B = mean over batch, σ²_B = variance over batch
x̂ = (x - μ_B) / sqrt(σ²_B + ε)
y = γ x̂ + β

## Benefits

- Stabilizes training, allows higher learning rates
- Reduces internal covariate shift
- Mild regularizing effect (batch statistics add noise)

LayerNorm is the layer-wise variant used in transformers, where batch size is often 1.
