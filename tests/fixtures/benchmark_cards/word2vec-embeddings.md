---
id: word2vec-embeddings
title: Word2Vec — Word Embeddings
type: knowledge
topic: representation-learning
tags:
  - word2vec
  - embeddings
  - CBOW
  - skip-gram
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Word2Vec learns dense vector representations of words by training on a self-supervised objective over a text corpus. Two variants: Continuous Bag-of-Words (CBOW) predicts a target word from context; Skip-gram predicts context from a target word.

## Skip-gram Objective

L = -Σ_{c∈C(t)} log P(w_c | w_t)

P(w_c | w_t) = exp(v_w_c · v_w_t) / Σ exp(v_w · v_w_t)

(negative sampling approximates the denominator).

## Properties

Embeddings capture semantic regularities: vec(king) - vec(man) + vec(woman) ≈ vec(queen). They are the precursor to contextualized representations in BERT and GPT.
