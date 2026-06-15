---
id: bayesian-inference
title: Bayesian Inference
type: knowledge
topic: statistics
tags:
  - bayesian
  - posterior
  - prior
  - likelihood
source_refs:
  - local:seed
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Definition

Bayesian inference updates beliefs about parameters θ given data x by combining a prior p(θ) with a likelihood p(x|θ) to obtain a posterior p(θ|x).

## Bayes' Theorem

p(θ|x) = p(x|θ) p(θ) / p(x)

The denominator p(x) = ∫ p(x|θ) p(θ) dθ is often intractable, motivating MCMC and variational methods.

## Conjugate Priors

When prior and posterior are in the same family (e.g., Beta-Bernoulli), the posterior has closed form. Otherwise approximate inference is required.
