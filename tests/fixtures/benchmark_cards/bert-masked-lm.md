---
id: bert-masked-lm
title: BERT — Bidirectional Encoder Representations
type: knowledge
topic: nlp
tags:
  - BERT
  - masked-language-model
  - transformer
  - pretraining
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

BERT (Bidirectional Encoder Representations from Transformers) is a masked-language-model pretraining objective for transformer encoders. Tokens are randomly masked and the model predicts them using bidirectional context.

## Pretraining Tasks

1. Masked Language Model (MLM): predict masked tokens
2. Next Sentence Prediction (NSP): predict sentence continuity

## Downstream Use

Fine-tuning the pretrained BERT on downstream tasks (classification, NER, QA) set SOTA on GLUE and SQuAD at release.
