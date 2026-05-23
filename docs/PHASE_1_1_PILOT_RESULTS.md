# Phase 1.1 Pilot Results - logit-normal vs Beta-Beta hierarchy

**Generated:** 2026-04-26 by tools/pilot_phase11_hierarchy.py
**Purpose:** ADR §3.A1 - validate prior choice before 12-15h Phase 1.1 implementation.

## Synthetic data
- n_obs: 36
- n_channels: 5
- True decays: [0.45, 0.4, 0.1, 0.08, 0.05]

## Beta-Beta hierarchy

```
  parameterization: beta_beta
  elapsed:          18.0 s
  divergences:      39
  R-hat max:        1.000
  ESS bulk min:     1495
  recovery 90% HDI: 5/5 (100%)
  per-channel:
    ch0: true=0.45 posterior_mean=0.28 HDI=[0.00,0.57]
    ch1: true=0.40 posterior_mean=0.22 HDI=[0.00,0.58]
    ch2: true=0.10 posterior_mean=0.06 HDI=[0.00,0.17]
    ch3: true=0.08 posterior_mean=0.04 HDI=[0.00,0.10]
    ch4: true=0.05 posterior_mean=0.10 HDI=[0.00,0.23]
```

## Logit-normal hierarchy

```
  parameterization: logit_normal
  elapsed:          15.3 s
  divergences:      7
  R-hat max:        1.000
  ESS bulk min:     4940
  recovery 90% HDI: 4/5 (80%)
  per-channel:
    ch0: true=0.45 posterior_mean=0.21 HDI=[0.00,0.47]
    ch1: true=0.40 posterior_mean=0.18 HDI=[0.00,0.39]
    ch2: true=0.10 posterior_mean=0.10 HDI=[0.00,0.19]
    ch3: true=0.08 posterior_mean=0.08 HDI=[0.00,0.16]
    ch4: true=0.05 posterior_mean=0.12 HDI=[0.00,0.22]
```

## Verdict

- Recovery: Beta-Beta 100%, logit-normal 80%
- Divergences: Beta-Beta 39, logit-normal 7
- Time ratio (LN/BB): 0.85×

**RECOMMENDATION: Adopt logit-normal** (fewer divergences, comparable speed).

Refs: docs/SPRINT1_FOUNDATION_ADR.md §3.A1, §5 Phase 1.1 plan