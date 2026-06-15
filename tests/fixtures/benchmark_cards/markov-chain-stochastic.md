---
id: markov-chain-stochastic
title: Markov Chain — Stochastic Process
type: knowledge
topic: probability
tags:
  - markov-chain
  - stochastic-process
  - transition-matrix
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

A Markov chain is a discrete-time stochastic process {X_t} satisfying the Markov property: future evolution depends only on the current state, not on history.

## Transition Matrix

P_ij = P(X_{t+1} = j | X_t = i)

## Stationary Distribution

A distribution π satisfying π P = π is stationary. Under irreducibility and aperiodicity, the chain converges to π regardless of initial state.
