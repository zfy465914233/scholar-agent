---
id: lstm-sequence-modeling
title: LSTM — Long Short-Term Memory Networks
type: knowledge
topic: neural-architecture
tags:
  - LSTM
  - recurrent-neural-network
  - sequence-modeling
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Long Short-Term Memory (LSTM) is a recurrent neural network architecture with a memory cell and three gating mechanisms (input, forget, output) that control information flow. It addresses the vanishing-gradient problem of vanilla RNNs.

## Gating Equations

i_t = σ(W_i x_t + U_i h_{t-1} + b_i)   (input gate)
f_t = σ(W_f x_t + U_f h_{t-1} + b_f)   (forget gate)
o_t = σ(W_o x_t + U_o h_{t-1} + b_o)   (output gate)
c_t = f_t ⊙ c_{t-1} + i_t ⊙ tanh(...)
h_t = o_t ⊙ tanh(c_t)

## Position vs Transformers

LSTMs dominated sequence modeling pre-2018. Transformers replaced them for most tasks due to parallelism, but LSTMs remain competitive for low-latency on-device inference.
