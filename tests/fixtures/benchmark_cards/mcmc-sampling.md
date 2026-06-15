---
id: mcmc-sampling
title: Markov Chain Monte Carlo (MCMC)
type: knowledge
topic: statistics
tags:
  - MCMC
  - markov-chain
  - sampling
  - metropolis-hastings
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Markov Chain Monte Carlo (MCMC) samples from a probability distribution by constructing a Markov chain whose stationary distribution equals the target. After burn-in, samples approximate the target.

## Metropolis-Hastings

Accept a proposed move θ' with probability:

α = min(1, [p(θ'|x) q(θ|θ')] / [p(θ|x) q(θ'|θ)])

## Applications

MCMC is the workhorse of Bayesian inference when the posterior is intractable. Hamiltonian Monte Carlo (HMC) and No-U-Turn Sampler (NUTS) are modern variants used in Stan and PyMC.
