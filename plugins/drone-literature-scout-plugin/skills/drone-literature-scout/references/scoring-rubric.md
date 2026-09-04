# Dynamic Direction Scoring

Keep 0–15 directions. No fixed direction is a baseline. Generate themes from all accepted rows and retain a direction only when its hard gates pass.

## Weighted score

Each dimension is 1–5. Compute:

```text
0.05 recommendation
+ 0.15 prospect
+ 0.25 feasibility
+ 0.10 RAL/ICRA/IROS venue fit
+ 0.25 uniqueness
+ 0.05 evidence density
+ 0.15 learning-method fit
```

Round to two decimals. Report each component and the weighted result; never hide a hard-gate failure behind a high score.

## Scheme A anchors

- **Feasibility 9-10:** official evidence supports the RTX 4090 single-digit-hours or RTX 5070 Ti within-one-day target and Jetson-class deployment; 4-6 means one or both are unknown; 0-3 means explicit over-budget or above-Jetson requirements.
- **Uniqueness 9-10:** a non-obvious perception-control learning problem with a clear gap and publication ceiling; 1-3 includes generic single-UAV obstacle avoidance, generic multi-UAV collaboration, or ordinary path planning.
- **Learning fit 9-10:** Isaac Lab/vectorized RL, residual/safe RL, differentiable simulation, or efficient domain randomization is central; 1-3 is pure classical planning/control.
- **Evidence:** abstract-only evidence can establish relevance, but only official full text or supplements can support compute, latency, memory, power, training-time, or experiment-number claims.
## Dimension anchors

- **Recommendation:** matches the researcher’s implementation/RL strengths and one-year target.
- **Prospect:** 2025–2026 activity, unsolved problem, and credible demand.
- **Feasibility:** sensor, flight-space, training, deployment, and validation fit.
- **Venue fit:** credible route to RAL/ICRA/IROS; reference-only venues are evidence, not automatic targets.
- **Uniqueness:** meaningful gap without requiring a huge infrastructure advantage.
- **Evidence density:** number and quality of independent accepted papers.
- **Learning fit:** RL, imitation, self-supervision, residual learning, or end-to-end learning is central; pure model-driven control scores lower.

## Pool changes

- Add a theme with at least 3 strong supporting papers, or 1 high-impact paper plus feasibility evidence.
- Remove after two consecutive cycles below 2.5 with no improvement signal.
- Keep a rank-11–15 direction when it is feasible and distinct; do not delete it merely because ten slots are already full.
- Record every add/remove/rank change in `研究方向分析.md`.
