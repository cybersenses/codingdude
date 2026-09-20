# LLM & AI feature checklist

As of: 2026-09-20
Source: https://raw.githubusercontent.com/msitarzewski/agency-agents/main/engineering/engineering-ai-engineer.md
Use when: building AI/ML-powered features or integrating LLMs into a system.

## Checklist
- [ ] Success metric defined before building: accuracy/F1/business KPI target the feature must hit.
- [ ] Model/feature served behind an API with auth, rate limiting, and versioning; model artifacts versioned (MLflow or equivalent).
- [ ] Latency budget chosen deliberately per pattern: real-time sync (<100ms), batch async, streaming, or on-device edge — hybrid where cost/latency demand.
- [ ] Drift monitoring: input data quality + model performance tracked; automated retraining triggers defined.
- [ ] A/B testing with statistical significance for model changes; canary deployment for new model versions.
- [ ] Cost per prediction measured and budgeted; compression/efficient inference where scale demands.
- [ ] Bias testing across demographic groups with fairness metrics where decisions affect people.
- [ ] Human oversight path for consequential outputs; content-safety/harm-prevention measures built in, not bolted on.
- [ ] Privacy: personal data in training/inference handled per the privacy checklist (minimization, retention, delete path).
- [ ] RAG/LLM specifics (from practice): eval set for prompt/agent changes, deterministic seams for testing, observability on tokens/cost/latency per request.

## Failure modes
- Model shipped with no drift monitoring — silently degrades as the world changes.
- Prompt/agent changes deployed with no eval harness — regressions invisible until users report.
- Accuracy reported as a vanity number with no business metric attached.
- "AI feature" with no human path for wrong outputs in consequential decisions.

## Rejected
- Training-infra depth (distributed training, ensembles), framework catalogs, ethics boilerplate without mechanism.
- Skipped: engineering-multi-agent-systems-architect (29KB) — domain is our home turf; we have stronger in-repo practice than the checklist would add.
