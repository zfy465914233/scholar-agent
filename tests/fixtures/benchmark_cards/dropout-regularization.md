---
id: dropout-regularization
title: Dropout for Neural Network Regularization
type: knowledge
topic: regularization
tags:
  - dropout
  - regularization
  - neural-network
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Dropout is a regularization technique for neural networks: during training, randomly set a fraction p of activations to zero. At test time, all activations are used (scaled by 1-p).

## Effect

Forces redundancy in representations — no single neuron can dominate. Equivalent to approximate Bayesian model averaging over thinned subnetworks.

## Typical Setup

- Drop rate p = 0.5 on hidden layers
- Lower (0.1-0.3) on inputs
- Often combined with L2 weight decay

Dropout is to neural networks what bagging is to decision trees: an ensemble of thinned models sharing parameters.
