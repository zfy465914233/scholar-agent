---
id: ddpm-diffusion
title: Denoising Diffusion Probabilistic Models
type: knowledge
topic: generative-models
tags:
  - diffusion
  - generative-model
  - DDPM
  - denoising
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Denoising Diffusion Probabilistic Models (DDPM) learn to generate data by reversing a gradual noising process. Training diffuses data into Gaussian noise over T steps; sampling then denoises from pure noise back to a clean sample.

## Forward Process

The diffusion process adds noise according to a variance schedule {β_1, ..., β_T}:

q(x_t | x_{t-1}) = N(x_t; sqrt(1-β_t) x_{t-1}, β_t I)

## Reverse Process

The model learns p_θ(x_{t-1} | x_t), denoising one step at a time. Each denoising step is parameterized by a U-Net with the same noise prediction across all timesteps.
