# Screening Criteria

## Hard gates

| Gate | Accept | Reject or hold |
|---|---|---|
| Vehicle | One UAV, or one UAV + ground vehicle/device | swarm, multi-UAV, formation, multi-agent, USV, underwater, pure UGV |
| Task | Perception input and control/closed-loop output | pure detection, classification, dataset, survey, communication, pure dynamics |
| Source | Official page in the venue whitelist | arXiv-only, MDPI, IEEE Access, Frontiers, TAI, TCST, unknown “IEEE” |
| Hardware | Feasible on Jetson Orin NX; training plausible on one 12GB GPU in about one day | explicit multi-A100/H100, >12GB-only training, special event camera dependency |
| Fit | Autonomous UAV flight, indoor/outdoor useful | language-conditioned/VLA/VLM/LLM, diffusion-training mainline, high-speed acrobatic flight as the core task |

## Scheme A direction-promotion gates

A paper may pass the corpus gates while still being held from direction promotion. Promotion requires all of the following:

- Learning fit: RL, residual RL, safe RL, differentiable simulation, domain randomization, or another trainable control mechanism is central; Isaac Lab/vectorized RL is preferred.
- Training target: the proposed experiment should fit RTX 4090 single-digit hours or RTX 5070 Ti within one day. Treat this as a project budget target, never as an unstated paper measurement.
- Deployment target: the complete perception-control loop must be plausible on Jetson-class hardware. Above-Jetson, multi-GPU-only, or large-memory-model requirements are hard rejects for the promoted pool.
- Novelty: generic single-UAV obstacle avoidance, generic multi-UAV collaboration, and ordinary path planning are baseline/reference topics, not high-ranked directions.
- Evidence: unknown training/deployment status is `待核验`; it may stay in the CSV with a complete official abstract, but it cannot justify quantitative feasibility or a final recommendation.
## Time range

- Non-strong-group work: prefer 2023–2026.
- Strong-group work: allow 2020–2026 for foundational evidence.
- Do not discover or promote 2019-and-earlier work during new searches unless the user explicitly asks for history.

## Evidence checklist

- [ ] Official title and venue page opened.
- [ ] DOI or official URL stored.
- [ ] Venue abbreviation exactly matches the whitelist.
- [ ] Vehicle and task pass the hard gates.
- [ ] Training/deployment feasibility assessed; unknown is marked, not invented.
- [ ] Lab group is identified from authors/institution or set to `否`.
- [ ] Title/URL/DOI/arXiv ID checked against the full CSV.
- [ ] Exclusion reason recorded for rejected candidates.
