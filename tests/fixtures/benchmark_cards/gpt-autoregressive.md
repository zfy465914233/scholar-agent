---
id: gpt-autoregressive
title: GPT — Autoregressive Language Models
type: knowledge
topic: nlp
tags:
  - GPT
  - autoregressive
  - decoder-only
  - language-model
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

GPT (Generative Pre-trained Transformer) is a decoder-only transformer trained autoregressively to predict the next token. The model generates text by sampling one token at a time conditioned on the prefix.

## Objective

L = -Σ log P(x_t | x_{<t})

## Scaling

GPT-3 (175B parameters) demonstrated that scaling autoregressive language models produces in-context learning — the ability to perform new tasks from examples in the prompt, without gradient updates.
