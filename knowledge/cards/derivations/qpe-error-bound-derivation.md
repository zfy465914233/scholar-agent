---
id: qpe-error-bound-derivation
title: QPE Error Bound Derivation Sketch
type: derivation
topic: quantum_computing
tags:
  - qpe
  - quantum-phase-estimation
  - error-bound
source_refs:
  - local:domain-seed
confidence: draft
updated_at: 2026-04-01
origin: local_seed
prerequisites:
  - quantum-fourier-transform
  - eigenphase
steps:
  - claim: Phase estimation accuracy improves with the number of counting qubits.
    support: standard QPE derivation structure
  - claim: The success probability concentrates around the closest binary approximation of the target phase.
    support: amplitude analysis after inverse QFT
---

## Goal

Capture the standard derivation idea behind the error bound and success probability in quantum phase estimation.

## Setup

Let the target eigenphase be `phi` and let `t` counting qubits be used so the algorithm resolves `phi` on a `2^t` grid.

## Derivation

After phase kickback, the counting register stores a superposition whose amplitudes depend on the phase mismatch between `phi` and each discrete grid point. Applying the inverse QFT concentrates mass near the closest `t`-bit approximation of `phi`.

The more counting qubits we use, the finer the discretization grid becomes, so the approximation error shrinks like the grid spacing. The success bound is then obtained by lower-bounding the probability mass in the interval around the nearest approximation.

## Source Support

This card is a sketch only. It is meant to anchor later import of a full derivation from a textbook or paper-backed source.

## Checks

When upgrading this card, add the explicit probability bound and one worked example.

