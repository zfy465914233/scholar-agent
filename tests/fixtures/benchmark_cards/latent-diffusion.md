---
id: latent-diffusion
title: Latent Diffusion Models (Stable Diffusion)
type: knowledge
topic: generative-models
tags:
  - latent-diffusion
  - LDM
  - stable-diffusion
  - generative-model
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Latent Diffusion Models (LDM) apply the diffusion process in a compressed latent space rather than pixel space. Stable Diffusion is the best-known instantiation, conditioned on text via CLIP embeddings.

## Two-Stage Pipeline

1. Train an autoencoder (VAE) that maps pixels ↔ latent
2. Run diffusion in the latent space, conditioned on text embeddings

## Efficiency

Operating in latent space reduces compute by ~8× compared to pixel-space diffusion, enabling high-resolution image generation on consumer GPUs.
