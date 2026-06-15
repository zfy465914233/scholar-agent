---
id: transformer-attention
title: Transformer Self-Attention Mechanism
type: knowledge
topic: neural-architecture
tags:
  - transformer
  - attention
  - self-attention
  - MHA
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

The Transformer replaces recurrence with self-attention, computing pairwise interactions between all tokens in a sequence. Multi-head attention (MHA) runs several attention heads in parallel to capture different relations.

## Scaled Dot-Product Attention

Attention(Q, K, V) = softmax(QK^T / sqrt(d_k)) V

Each token attends to every other token, weighted by query-key similarity.

## Complexity

Self-attention scales as O(n²) with sequence length n, motivating FlashAttention and sparse variants.
