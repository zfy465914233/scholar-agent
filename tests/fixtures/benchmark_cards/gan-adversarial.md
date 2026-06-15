---
id: gan-adversarial
title: Generative Adversarial Networks (GAN)
type: knowledge
topic: generative-models
tags:
  - GAN
  - adversarial
  - generative-model
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

A Generative Adversarial Network (GAN) pits a generator G against a discriminator D in a two-player minimax game. G maps noise z to samples; D tries to distinguish real from fake.

## Objective

min_G max_D E[log D(x)] + E[log(1 - D(G(z)))]

## Modes of Failure

- Mode collapse: G produces limited variety
- Training instability: D and G must stay balanced

GANs complement diffusion models — GANs offer fast sampling, diffusion offers stable training.
