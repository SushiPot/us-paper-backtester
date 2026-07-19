# ADR 0003: Block New Simulated Buys Until Profit Evidence Improves

## Status

Accepted

## Context

The local paper account is currently slightly negative, the benchmark gate says the account is lagging, signal evaluation has low precision/F1, and Factor Lab marks the leading factor as weak. The program runs reliably, but the current evidence does not support increasing simulated risk.

## Decision

Add a Profit Quality Gate before new local paper buys. The gate requires positive signal evidence, non-weak factor evidence, and no losing/lagging benchmark state before a new simulated long entry can pass. Existing sell and risk-reducing behavior remains unchanged.

## Consequences

- The simulator should trade less while evidence is weak.
- Cash preservation becomes the default when signal quality is poor.
- Users can loosen or disable the gate with environment variables for experiments; these settings are read by the local paper runtime itself.
- This does not guarantee profit; it only prevents weak-evidence new buys from compounding losses.
