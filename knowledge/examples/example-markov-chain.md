---
id: example-markov-chain-definition
title: Markov Chain — Definition
type: definition
topic: examples
tags:
  - example
  - markov-chain
  - probability
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

A Markov chain is a stochastic process {X_t} satisfying the Markov property: the future state depends only on the current state, not on the sequence of events that preceded it.

P(X_{t+1} = s | X_t = s_t, X_{t-1} = s_{t-1}, ...) = P(X_{t+1} = s | X_t = s_t)

## Key Properties

- **State space**: finite or countable set of states
- **Transition matrix**: P_ij = P(X_{t+1} = j | X_t = i)
- **Stationary distribution**: pi such that pi * P = pi
- **Irreducibility**: every state can be reached from every other state
- **Aperiodicity**: the chain does not cycle between states

## See Also

- Stationary distribution derivation
- Markov chain Monte Carlo (MCMC)
