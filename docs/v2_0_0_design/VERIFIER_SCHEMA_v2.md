# Methodology Certificate Schema v2.0.0 — Verifier Update Spec

**Audience:** Маша небесная (owner of `verify.auroraai.pro`,
`aurora-platform-core/c7-web-verifier`)
**Date:** 2026-05-14
**Status:** Spec ready for verifier-side update — coordinate when convenient
**Author:** Маша маленькая
**Related:** ADR-019 §11, PRE_FLIGHT_FIXES §N7, ENGINEERING_INVARIANTS §INV-06

---

## Context

Aurora MMM Optimizer v2.0.0 adds v2.0.0 fields to the Methodology Certificate
(per ADR-019). The Optimizer-side implementation is in:

- `sidecar/econometrica/engines/methodology_cert.py` — builds + hashes payload
- `sidecar/econometrica/requirements.txt` — added `rfc8785>=0.1.2`

The verifier (`c7-web-verifier`) needs to be updated to parse + verify the new
schema. This doc is the spec for that update.

**No deadline.** v2.0.0 Optimizer ships with graceful degradation: v2.0.0
certificates are backward-compatible with the existing verifier (old verifier
verifies the v1.3.x fields subset and shows `VERIFIED_WITH_CAVEATS` if
`certificate_version` field is present but unknown). Full v2.0.0 verification
activates after the verifier update.

---

## Hash algorithm (unchanged)

JCS RFC 8785 canonical JSON → SHA-256.

Rust: `serde_jcs` (already used in c7-web-verifier per INV-06).
Python: `rfc8785` package (new dep in Optimizer sidecar, see requirements.txt).

---

## Certificate payload schema changes

### Dispatch field (new)

```json
{
  "certificate_version": "2.0.0"
}
```

- If field is absent → treat as `"1.3"` (backward compat).
- If value is `"1.3"` → verify v1.3.x fields only.
- If value is `"2.0.0"` → verify full v2.0.0 payload (v1.3.x fields + v2.0.0 additive fields).

### v1.3.x fields (preserved byte-identical)

```json
{
  "bundle_manifest_hash": "<sha256-hex of bundle manifest.json>",
  "model_spec": {
    "kpi_type": "sales_packs",
    "kpi_likelihood": "normal",
    "num_channels": 5,
    "adstock_types": {"TV": "geometric", "Digital": "weibull"}
  },
  "decomposition_summary": {
    "Base": {"value": 147000, "contribution_pct": 60.0},
    "TV": {"value": 49000, "contribution_pct": 20.0},
    "Digital": {"value": 24500, "contribution_pct": 10.0}
  },
  "channel_roi": {
    "TV": {"roi": 3.2, "roi_ci_low": 2.8, "roi_ci_high": 3.7},
    "Digital": {"roi": 2.1, "roi_ci_low": 1.8, "roi_ci_high": 2.5}
  }
}
```

These fields are preserved **byte-identical** between v1.3.x and v2.0.0
certificates so that the existing verifier can still verify v2.0.0 certs via
the v1.3.x subset.

### v2.0.0 additive fields

```json
{
  "analysisMode": "roi",

  "signed_factor_contributions": {
    "competitor_trp": {
      "value": -26950,
      "pct": -11.0,
      "ci_90": [-32000, -22000],
      "type": "signed_competitor",
      "beta_mean": -0.18
    },
    "price_average": {
      "value": -7350,
      "pct": -3.0,
      "type": "signed_price",
      "beta_mean": -0.09
    },
    "holiday_newyear_preshop": {
      "value": 4900,
      "pct": 2.0,
      "type": "holiday",
      "beta_mean": 0.12
    },
    "holiday_march8": {
      "value": 7350,
      "pct": 3.0,
      "type": "holiday",
      "beta_mean": 0.15
    }
  },

  "holiday_dummies_injected": [
    "holiday_feb23",
    "holiday_march8",
    "holiday_may1",
    "holiday_may9",
    "holiday_june12",
    "holiday_newyear_preshop",
    "holiday_newyear_jan1_2"
  ],

  "mcmc_diagnostics": {
    "r_hat_max": 1.02,
    "ess_min": 1240
  },

  "backtest_results": {
    "mape": 8.2,
    "rmse": 1400.0,
    "r2": 0.91
  },

  "ppc_results": {
    "r2": 0.91,
    "durbin_watson": 1.95
  }
}
```

**Type notes:**
- `analysisMode`: `"roi"` | `"effectiveness"` | `"mixed"` (string enum)
- `signed_factor_contributions`: keys = column names. Values: `value` and `pct`
  may be negative (competitor effects, price elasticity). `ci_90` optional.
  `type`: `"signed_competitor"` | `"signed_price"` | `"signed_weather"` |
  `"signed_macro"` | `"holiday"`
- `holiday_dummies_injected`: sorted list of strings (sorted for JCS stability)
- `mcmc_diagnostics.r_hat_max`: R-hat threshold for VERIFIED = ≤ 1.05 (per
  WIZARD_FLOW §6.2). Values > 1.1 = CONVERGENCE_WARNING.
- `mcmc_diagnostics.ess_min`: ESS threshold for VERIFIED = ≥ 400 (per
  WIZARD_FLOW §6.2). Values < 200 = ESS_WARNING.
- `backtest_results.mape`: percent (e.g., 8.2 = 8.2%)
- `ppc_results.durbin_watson`: DW statistic; VERIFIED range = [1.5, 2.5]

---

## Full v2.0.0 certificate payload (complete example)

```json
{
  "certificate_version": "2.0.0",
  "bundle_manifest_hash": "a3f8c2d1e4b6...",
  "model_spec": {
    "kpi_type": "sales_packs",
    "kpi_likelihood": "normal",
    "num_channels": 4,
    "adstock_types": {"TV": "geometric", "Digital": "geometric", "OOH": "geometric", "Radio": "geometric"}
  },
  "decomposition_summary": {
    "Base": {"value": 147000, "contribution_pct": 60.0},
    "TV": {"value": 49000, "contribution_pct": 20.0},
    "Digital": {"value": 24500, "contribution_pct": 10.0},
    "OOH": {"value": 9800, "contribution_pct": 4.0},
    "Radio": {"value": 4900, "contribution_pct": 2.0},
    "SignedFactors": {"value": -9800, "contribution_pct": -4.0}
  },
  "channel_roi": {
    "TV": {"roi": 3.2, "roi_ci_low": 2.8, "roi_ci_high": 3.7},
    "Digital": {"roi": 2.1, "roi_ci_low": 1.8, "roi_ci_high": 2.5},
    "OOH": {"roi": 1.4, "roi_ci_low": 1.1, "roi_ci_high": 1.8},
    "Radio": {"roi": 0.9, "roi_ci_low": 0.6, "roi_ci_high": 1.3}
  },
  "analysisMode": "roi",
  "signed_factor_contributions": {
    "competitor_trp": {"value": -26950, "pct": -11.0, "type": "signed_competitor", "beta_mean": -0.18},
    "price_average": {"value": -7350, "pct": -3.0, "type": "signed_price", "beta_mean": -0.09},
    "holiday_newyear_preshop": {"value": 4900, "pct": 2.0, "type": "holiday", "beta_mean": 0.12},
    "holiday_march8": {"value": 7350, "pct": 3.0, "type": "holiday", "beta_mean": 0.15}
  },
  "holiday_dummies_injected": [
    "holiday_feb23",
    "holiday_march8",
    "holiday_may1",
    "holiday_newyear_preshop"
  ],
  "mcmc_diagnostics": {"r_hat_max": 1.02, "ess_min": 1240},
  "backtest_results": {"mape": 8.2, "rmse": 1400.0, "r2": 0.91},
  "ppc_results": {"r2": 0.91, "durbin_watson": 1.95}
}
```

---

## Verifier-side changes needed

### 1. Parser (`src/parser.rs`)

```rust
// Extend CertPayload struct (or use serde_json::Value for additive fields).

#[derive(Debug, Deserialize)]
struct CertPayload {
    // Dispatch
    #[serde(default = "default_cert_version")]
    certificate_version: String,

    // v1.3.x fields (existing)
    bundle_manifest_hash: String,
    model_spec: serde_json::Value,
    decomposition_summary: HashMap<String, ContribEntry>,
    channel_roi: HashMap<String, RoiEntry>,

    // v2.0.0 additive (all Option<> for backward compat)
    #[serde(default)]
    analysis_mode: Option<String>,
    #[serde(default)]
    signed_factor_contributions: Option<serde_json::Value>,
    #[serde(default)]
    holiday_dummies_injected: Option<Vec<String>>,
    #[serde(default)]
    mcmc_diagnostics: Option<McmcDiag>,
    #[serde(default)]
    backtest_results: Option<BacktestSummary>,
    #[serde(default)]
    ppc_results: Option<PpcSummary>,
}

fn default_cert_version() -> String { "1.3".to_string() }
```

### 2. Hash recomputation logic

```rust
fn verify_cert_hash(payload: &CertPayload, claimed_hash: &str) -> VerifyResult {
    // Re-serialize with serde_jcs (JCS RFC 8785) — bit-stable per INV-06.
    let canonical = serde_jcs::to_string(payload)?;
    let actual_hash = hex::encode(sha2::Sha256::digest(canonical.as_bytes()));

    if actual_hash != claimed_hash {
        return VerifyResult::HashMismatch { actual, claimed };
    }

    // Additional semantic checks for v2.0.0 (optional but recommended):
    if payload.certificate_version == "2.0.0" {
        if let Some(mcmc) = &payload.mcmc_diagnostics {
            if mcmc.r_hat_max > 1.1 {
                return VerifyResult::VerifiedWithWarning {
                    warning: "MCMC R-hat > 1.1: convergence concern"
                };
            }
            if mcmc.ess_min < 200.0 {
                return VerifyResult::VerifiedWithWarning {
                    warning: "MCMC ESS < 200: low effective sample size"
                };
            }
        }
    }

    VerifyResult::Verified
}
```

**Key:** for v1.3.x certificates (`certificate_version == "1.3"`), the hash
covers only v1.3.x fields. Deserialize into a v1.3.x-only struct before
re-computing the hash (don't include v2.0.0 fields even if accidentally present
in the JSON — those weren't in the original hash input).

### 3. UI display on `verify.auroraai.pro`

New fields to surface in the verification result page:

```
Certificate version: 2.0.0

Analysis Mode: ROI (monetary channels)

Signed Factors:
  ↓ Competitor TRP    -11.0%   (-26,950 units)
  ↓ Price average     -3.0%    (-7,350 units)
  ↑ New Year pre-shop +2.0%    (+4,900 units)
  ↑ March 8           +3.0%    (+7,350 units)

Holidays injected: Feb 23 · Mar 8 · May 1 · New Year Pre-Shop
  (4 of 12 РФ events present in training data)

MCMC Convergence:
  R-hat max: 1.02  ✓ (threshold ≤ 1.05)
  ESS min:   1240  ✓ (threshold ≥ 400)

Backtest (holdout validation):
  MAPE: 8.2%   ✓ (excellent ≤ 10%)
  RMSE: 1,400
  R²:   0.91   ✓ (excellent ≥ 0.80)

Posterior Predictive Check:
  R²:            0.91   ✓
  Durbin-Watson: 1.95   ✓ (range 1.5–2.5)
```

**Traffic-light thresholds:**

| Metric | Green (✓) | Yellow (⚠) | Red (✗) |
|---|---|---|---|
| R-hat max | ≤ 1.05 | 1.05–1.10 | > 1.10 |
| ESS min | ≥ 400 | 200–400 | < 200 |
| MAPE | ≤ 10% | 10–20% | > 20% |
| Backtest R² | ≥ 0.80 | 0.60–0.80 | < 0.60 |
| Durbin-Watson | 1.5–2.5 | 1.0–1.5 or 2.5–3.0 | < 1.0 or > 3.0 |

(Per WIZARD_FLOW_v2_FINAL.md §6.2 — Маша маленькая can update if thresholds change.)

---

## Backward-compat test matrix

| Test | Expected result |
|---|---|
| v1.3.x cert + old verifier (current) | VERIFIED |
| v1.3.x cert + new verifier | VERIFIED (unchanged, v1.3.x fields only) |
| v2.0.0 cert + new verifier | VERIFIED (full v2.0.0 hash check) |
| v2.0.0 cert + old verifier | VERIFIED_WITH_CAVEATS (unknown `certificate_version` field, v1.3.x fields hash-match, new fields ignored per ADR-017 additive) |
| v2.0.0 cert, tampered `analysisMode` + new verifier | HASH_MISMATCH |
| v2.0.0 cert, tampered `channel_roi` + new verifier | HASH_MISMATCH |
| v2.0.0 cert, tampered `channel_roi` + old verifier | HASH_MISMATCH |

The last two rows confirm that channel ROI tampering is caught by both verifier
versions — the attack surface for the most commercially sensitive field.

---

## Implementation files

**Optimizer-side (committed by Маша маленькая, branch `feat/v2.0.0-explicit-mode-wizard`):**
- `sidecar/econometrica/engines/methodology_cert.py` — builds + hashes payload
- `sidecar/econometrica/requirements.txt` — added `rfc8785>=0.1.2`
- `docs/v2_0_0_design/VERIFIER_SCHEMA_v2.md` — this spec

**Verifier-side (Маша небесная, `aurora-platform-core/c7-web-verifier`):**
- `src/parser.rs` — extend CertPayload struct with v2.0.0 optional fields
- `src/verify.rs` — version-dispatch hash recomputation
- `src/ui/` — display v2.0.0 fields (traffic-light diagnostics, signed factors)
- WASM rebuild + redeploy `verify.auroraai.pro`

---

## Contact

Маша маленькая через `aurora-meta/INBOX_TO_MN_GIT_FALLBACK.md`
или Google Drive INBOX_TO_MN (folder `1e7EGvO9IxRDO58Hcyvuh7ImqBzk0g7Wz`).
