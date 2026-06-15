---
id: bm25-lexical-retrieval
title: BM25 — Lexical Retrieval Scoring
type: knowledge
topic: information-retrieval
tags:
  - BM25
  - Okapi
  - lexical-retrieval
  - ranking
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

BM25 (Best Matching 25) is the standard scoring function for lexical retrieval. It is a bag-of-words method that scores documents by term frequency with saturation and document-length normalization.

## Formula

score(q, d) = Σ IDF(q_i) · [f(q_i, d) · (k_1+1)] / [f(q_i, d) + k_1 · (1 - b + b · |d|/avgdl)]

## Parameters

- k_1 = 1.5 controls term-frequency saturation
- b = 0.75 controls length normalization

BM25 is the strong baseline that neural retrieval methods (e.g., DPR, ColBERT) are compared against. Hybrid retrieval blends BM25 with embedding similarity.
