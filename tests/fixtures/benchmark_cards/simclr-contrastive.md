---
id: simclr-contrastive
title: SimCLR — Contrastive Learning Framework
type: knowledge
topic: representation-learning
tags:
  - contrastive-learning
  - SimCLR
  - self-supervised
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

SimCLR (Simple Framework for Contrastive Learning of Representations) learns visual representations by pulling together augmentations of the same image (positive pairs) while pushing apart different images (negative pairs).

## InfoNCE Loss

L = -log [exp(sim(z_i, z_j)/τ) / Σ_k exp(sim(z_i, z_k)/τ)]

## Components

- Stochastic augmentations (crop, color jitter)
- Base encoder (ResNet)
- Projection head (MLP)
- Normalized temperature-scaled cross-entropy

Contrastive learning underlies modern multimodal models like CLIP.
