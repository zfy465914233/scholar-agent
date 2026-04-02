---
id: stationary-distribution-derivation
title: Stationary Distribution Derivation For A Finite Markov Chain
type: derivation
topic: stochastic_processes
tags:
  - markov-chain
  - stationary-distribution
  - linear-algebra
source_refs:
  - local:seed-card
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
prerequisites:
  - markov-chain-definition
  - transition-matrix
steps:
  - claim: A stationary distribution is a row vector pi satisfying pi P = pi.
    support: definition of invariance under one transition step
  - claim: Rearranging gives (P^T - I) pi^T = 0 together with sum(pi_i) = 1.
    support: linear algebra reformulation plus probability normalization
  - claim: Solving this constrained linear system yields candidate stationary distributions.
    support: finite-state linear system solution
---

## Goal

Derive the standard linear system used to compute a stationary distribution for a finite-state Markov chain.

## Setup

Let `P` be the transition matrix of a finite Markov chain and let `pi` be a row vector of state probabilities.

## Derivation

If `pi` is unchanged after one transition step, then applying `P` to `pi` must reproduce `pi` itself. This gives the invariance equation `pi P = pi`.

Move all terms to one side to obtain `pi P - pi = 0`. Taking transposes gives `(P^T - I) pi^T = 0`.

Because `pi` is a probability distribution, its entries must sum to one and must be nonnegative. So the computational problem becomes: solve the homogeneous linear system together with the normalization constraint `sum(pi_i) = 1`.

## Source Support

The invariance equation and normalization condition are directly source-backed mathematical definitions. The computational interpretation as a constrained linear system is an immediate algebraic consequence.

## Checks

After solving, verify:

1. `pi_i >= 0` for every state
2. `sum(pi_i) = 1`
3. `pi P = pi` up to numerical tolerance
