---
id: markov-chain-definition
title: Markov Chain Definition
type: definition
topic: stochastic_processes
tags:
  - markov-chain
  - probability
  - state-transition
source_refs:
  - local:seed-card
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Core Statement

A Markov chain is a stochastic process whose next-state distribution depends only on the current state, not on the full past history.

## Formal Definition

For states `X_0, X_1, ..., X_n`, the Markov property is:

`P(X_{n+1} = x | X_n, X_{n-1}, ..., X_0) = P(X_{n+1} = x | X_n)`

whenever the conditional probabilities are well-defined.

## Intuition

The present state carries all the information needed to describe the distribution of the next step.

## Usage Notes

This definition is the entry point for transition matrices, stationary distributions, irreducibility, and mixing behavior.

## Related Concepts

- transition matrix
- stationary distribution
- irreducibility

