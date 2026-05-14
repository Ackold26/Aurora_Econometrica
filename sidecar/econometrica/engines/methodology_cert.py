"""Methodology Certificate — hash generation for Aurora MMM Optimizer.

Computes a cryptographic hash (SHA-256 over JCS RFC 8785 canonical JSON) that
covers the full methodology payload for a completed MMM run. The hash is
embedded in the exported HTML report and bundle manifest so that
`verify.auroraai.pro` (Rust WASM, aurora-platform-core/c7-web-verifier) can
independently verify the model artefacts haven't been tampered with.

INV-06 compliance: JCS RFC 8785 (`rfc8785` package) is used for bit-stable
canonical serialization — Pydantic / json.dumps key ordering are NOT used for
the cryptographic payload (see feedback_jcs_canonical_hash.md).

### Certificate versioning (additive, ADR-017 / ADR-019)

- `certificate_version` field signals which fields are covered by the hash.
- v1.3.x verifier: ignores unknown fields, verifies only v1.3.x payload subset.
- v2.0.0 verifier: full payload (v1.3.x fields + v2.0.0 additive fields).
- Old certificates (absent `certificate_version`): treated as "1.3" by verifier.

### Backward-compat contract (ADR-017 additive schema)

v1.3.x model → `build_cert_payload()` returns v1.3.x-only fields + a
`certificate_version: "1.3"` tag (no v2.0.0 fields included). The resulting
hash equals what the old verifier expects.

v2.0.0 model → full payload including v2.0.0 fields + `certificate_version:
"2.0.0"`. Old verifier ignores v2.0.0 fields (per ADR-017) and verifies v1.3.x
subset; new verifier verifies full payload.

Usage:
    from engines.methodology_cert import build_cert_payload, compute_cert_hash

    payload = build_cert_payload(model_data, decompose_result, bundle_manifest)
    cert_hash = compute_cert_hash(payload)
    # Embed cert_hash in bundle/manifest.json + HTML report header.

Reference:
    docs/v2_0_0_design/PRE_FLIGHT_FIXES.md §N7 (Methodology Certificate schema)
    docs/v2_0_0_design/VERIFIER_SCHEMA_v2.md (verifier-side spec)
    ENGINEERING_INVARIANTS.md §INV-06 (JCS canonical hash)
    ADR-019 §11 (Phase E5)
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# JCS RFC 8785 — bit-stable canonical JSON for cryptographic payloads (INV-06).
# Falls back to sorted-key json.dumps с warning if rfc8785 not installed.
# Production: rfc8785 must be present (added to requirements.txt).
try:
    import rfc8785  # type: ignore[import]
    _HAS_JCS = True
except ImportError:
    _HAS_JCS = False
    logger.warning(
        "rfc8785 not installed — falling back to sorted-key json.dumps for "
        "Methodology Certificate hash. Install rfc8785 for INV-06 compliance. "
        "Hash will NOT match verify.auroraai.pro (Rust/serde_jcs)."
    )


# ── Current certificate version ──────────────────────────────────────────────

CERT_VERSION_V13 = "1.3"
CERT_VERSION_V20 = "2.0.0"


# ── Canonical serialization (INV-06) ─────────────────────────────────────────

def _jcs_encode(payload: dict[str, Any]) -> bytes:
    """Encode payload as JCS RFC 8785 canonical JSON bytes.

    Per INV-06: rfc8785 is the primary path. Fallback (sorted json.dumps) is
    intentionally lossy для crypto — warns loudly. The fallback exists so
    integration tests pass in stripped environments; production MUST use rfc8785.
    """
    if _HAS_JCS:
        # rfc8785.dumps() returns bytes, deterministic per RFC 8785.
        return rfc8785.dumps(payload)  # type: ignore[no-any-return]
    else:
        # Fallback: json.dumps with sort_keys is NOT bit-stable across Python
        # versions or platforms for all types (floats, unicode NFC vs NFD, etc.)
        # but is the best we can do without rfc8785.
        return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")


def compute_cert_hash(payload: dict[str, Any]) -> str:
    """Compute SHA-256 hex digest of the JCS-canonical certificate payload.

    Returns:
        64-char lowercase hex string (SHA-256).
    """
    canonical = _jcs_encode(payload)
    return hashlib.sha256(canonical).hexdigest()


# ── Payload builders ──────────────────────────────────────────────────────────

def _extract_v13_payload(
    model_data: dict[str, Any],
    decompose_result: dict[str, Any],
    bundle_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Extract v1.3.x hash payload fields (preserved exactly for compat).

    These fields are the ones the existing verify.auroraai.pro verifier knows
    about. They MUST stay byte-identical between v1.3.x and v2.0.0 certificates
    so that old verifiers can still verify v2.0.0 certificates via the v1.3
    subset.

    Fields:
        bundle_manifest_hash: SHA-256 of the raw manifest JSON bytes (the
            manifest.json file content in the bundle directory). Covers bundle
            identity — data structure, data files checksum list.
        model_spec: prior distribution names + formula skeleton + inference
            settings. Does NOT include posterior samples (those are in pickle).
            Extracted from `model_data['diagnostics']['model_spec']` or
            reconstructed from model_data fields as fallback.
        decomposition_summary: per-category contribution totals + percentages,
            as returned by the decomposer. Covers «what the model said».
        channel_roi: per-channel ROI point estimates + 90% CI. Covers «what
            the optimizer computed».
    """
    # bundle_manifest_hash: hash of raw manifest JSON (must be pre-computed
    # by caller — we only include the hex string in the cert payload).
    bundle_hash = bundle_manifest.get('_cert_bundle_hash', '')
    if not bundle_hash:
        # Fallback: compute from manifest content itself (excludes _cert_* keys).
        clean_manifest = {k: v for k, v in bundle_manifest.items() if not k.startswith('_cert')}
        bundle_hash = compute_cert_hash(clean_manifest)

    # model_spec: extract from diagnostics or reconstruct from model_data.
    diagnostics = model_data.get('diagnostics') or {}
    model_spec_raw = diagnostics.get('model_spec') or {}
    if not model_spec_raw:
        # Reconstruct minimal spec from model_data fields for pre-diagnostics pickles.
        model_spec_raw = {
            'kpi_type': model_data.get('kpi_type', 'sales'),
            'kpi_likelihood': model_data.get('kpi_likelihood', 'normal'),
            'num_channels': len(model_data.get('channel_params', {}) or {}),
            'adstock_types': model_data.get('channel_adstock_types', {}) or {},
        }

    # decomposition_summary: per-category totals from decomposer output.
    waterfall = decompose_result.get('waterfall') or []
    decomp_summary: dict[str, Any] = {}
    for item in waterfall:
        cat = item.get('category') or item.get('name') or 'unknown'
        decomp_summary[str(cat)] = {
            'value': float(item.get('value') or 0),
            'contribution_pct': float(item.get('contribution_pct') or item.get('pct') or 0),
        }

    # channel_roi: per-channel ROI point estimates + 90% CI.
    channels_raw = decompose_result.get('channels') or []
    channel_roi: dict[str, Any] = {}
    for ch in channels_raw:
        name = ch.get('name') or ch.get('channel') or 'unknown'
        channel_roi[str(name)] = {
            'roi': float(ch.get('roi') or 0),
            'roi_ci_low': float(ch.get('roi_ci_low') or ch.get('roi_ci_90', [0, 0])[0] if isinstance(ch.get('roi_ci_90'), list) else 0),
            'roi_ci_high': float(ch.get('roi_ci_high') or ch.get('roi_ci_90', [0, 0])[-1] if isinstance(ch.get('roi_ci_90'), list) else 0),
        }

    return {
        'bundle_manifest_hash': bundle_hash,
        'model_spec': model_spec_raw,
        'decomposition_summary': decomp_summary,
        'channel_roi': channel_roi,
    }


def _extract_v20_fields(
    model_data: dict[str, Any],
    decompose_result: dict[str, Any],
) -> dict[str, Any]:
    """Extract v2.0.0 additive fields for the certificate hash payload.

    These fields are ADDITIVE to the v1.3.x payload. A v1.3.x verifier that
    doesn't know about them will skip them per ADR-017 additive schema; a
    v2.0.0 verifier includes them in the hash check.

    Fields per PRE_FLIGHT_FIXES §N7 + task spec:
        analysisMode: 'roi' | 'effectiveness' | 'mixed'
        signed_factor_contributions: full per-factor breakdown from decomposer
        holiday_dummies_injected: list of 12 РФ holiday event names present in
            training dataset (subset of the 12 hardcoded holidays from modeler.py)
        mcmc_diagnostics: r_hat_max, ess_min (convergence indicators)
        backtest_results: mape, rmse, r2 (holdout validation)
        ppc_results: r2, durbin_watson (posterior predictive check)
    """
    # analysisMode — recorded at train time (ADR-019 §1). Default 'roi' if
    # absent (pre-v2.0.0 pickle migrated into default per _inject_v20_defaults).
    analysis_mode = str(model_data.get('analysis_mode') or 'roi')

    # signed_factor_contributions — full breakdown from decomposer v2.0.0 output.
    # Key: factor name. Value: {value, pct, type, beta_mean}.
    # If decompose_result doesn't include signed_factors (v1.3.x decomposer),
    # fall back to reconstructing from model_data.normalization.
    signed_factors_raw = decompose_result.get('signed_factor_contributions') or {}
    if not signed_factors_raw:
        # Fallback reconstruction from control betas (same logic as json_export.py).
        norm = model_data.get('normalization') or {}
        control_cols = (model_data.get('config') or {}).get('control_columns') or []
        control_betas_mean = norm.get('control_betas_mean') or []
        if len(control_betas_mean) == len(control_cols):
            try:
                from utils.column_detection import classify_column  # type: ignore[import]
                for i, col in enumerate(control_cols):
                    kind = classify_column(col)
                    if kind in ('signed_competitor', 'signed_price', 'signed_weather',
                                'signed_macro', 'holiday'):
                        signed_factors_raw[str(col)] = {
                            'beta_mean': float(control_betas_mean[i]),
                            'type': kind,
                        }
            except Exception as exc:
                logger.warning('Signed factor reconstruction failed for cert: %s', exc)

    # Normalize: ensure all values are plain Python types (no numpy floats).
    signed_factors_cert: dict[str, Any] = {}
    for factor_name, factor_data in signed_factors_raw.items():
        signed_factors_cert[str(factor_name)] = {
            k: (float(v) if isinstance(v, (int, float)) else
                [float(x) for x in v] if isinstance(v, list) else str(v))
            for k, v in (factor_data or {}).items()
        }

    # holiday_dummies_injected — list of holiday dummy column names present in
    # training data (from persistence._inject_v20_defaults or set at train time).
    holidays_raw = model_data.get('holiday_dummies_injected') or []
    holidays_cert = sorted(str(h) for h in holidays_raw)  # sorted for JCS stability

    # mcmc_diagnostics — r_hat_max + ess_min summary.
    mcmc_raw = model_data.get('mcmc_diagnostics') or {}
    if isinstance(mcmc_raw, dict):
        mcmc_cert: dict[str, Any] = {
            'r_hat_max': float(mcmc_raw.get('r_hat_max') or 0),
            'ess_min': float(mcmc_raw.get('ess_min') or 0),
        }
    else:
        mcmc_cert = {'r_hat_max': 0.0, 'ess_min': 0.0}

    # backtest_results — summary metrics only (not per-period predictions, те
    # слишком большие для cert payload и не нужны для verification).
    backtest_raw = model_data.get('backtest_results') or {}
    if isinstance(backtest_raw, dict):
        metrics_raw = backtest_raw.get('metrics') or backtest_raw  # supports nested or flat
        backtest_cert: dict[str, Any] = {
            'mape': float(metrics_raw.get('mape') or metrics_raw.get('mape_pct') or 0),
            'rmse': float(metrics_raw.get('rmse') or 0),
            'r2': float(metrics_raw.get('r2') or metrics_raw.get('r_squared') or 0),
        }
    else:
        backtest_cert = {'mape': 0.0, 'rmse': 0.0, 'r2': 0.0}

    # ppc_results — r2 + durbin_watson summary.
    ppc_raw = model_data.get('ppc_results') or {}
    if isinstance(ppc_raw, dict):
        ppc_cert: dict[str, Any] = {
            'r2': float(ppc_raw.get('r2') or ppc_raw.get('r_squared') or 0),
            'durbin_watson': float(ppc_raw.get('durbin_watson') or ppc_raw.get('residual_durbin_watson') or 0),
        }
    else:
        ppc_cert = {'r2': 0.0, 'durbin_watson': 0.0}

    return {
        'analysisMode': analysis_mode,
        'signed_factor_contributions': signed_factors_cert,
        'holiday_dummies_injected': holidays_cert,
        'mcmc_diagnostics': mcmc_cert,
        'backtest_results': backtest_cert,
        'ppc_results': ppc_cert,
    }


def build_cert_payload(
    model_data: dict[str, Any],
    decompose_result: dict[str, Any],
    bundle_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build the full Methodology Certificate hash payload.

    Detects whether the model is v2.0.0 or v1.3.x (via `is_v20_compatible()`)
    and includes the corresponding fields.

    Args:
        model_data: loaded model dict from `persistence.load_model_with_compat()`.
        decompose_result: decomposer output dict (from `decomposer.decompose()`).
        bundle_manifest: bundle manifest dict (from manifest.json). May include
            `_cert_bundle_hash` pre-computed by caller (Rust side or Python
            bundle writer).

    Returns:
        Payload dict ready for `compute_cert_hash()`. Also returned to caller
        so it can be embedded in the bundle for transparency.
    """
    # Base v1.3.x payload (always present regardless of version).
    payload = _extract_v13_payload(model_data, decompose_result, bundle_manifest)

    # Detect v2.0.0 compatibility (uses persistence helper or fallback heuristic).
    try:
        from engines.persistence import is_v20_compatible  # type: ignore[import]
        is_v20 = is_v20_compatible(model_data)
    except ImportError:
        # Fallback: check model_version string directly.
        model_ver = str(model_data.get('model_version') or '1.3')
        is_v20 = model_ver.startswith('2.')

    if is_v20:
        # Additive v2.0.0 fields (old verifier gracefully ignores these per ADR-017).
        payload.update(_extract_v20_fields(model_data, decompose_result))
        payload['certificate_version'] = CERT_VERSION_V20
    else:
        # v1.3.x certificate — no v2.0.0 additive fields.
        payload['certificate_version'] = CERT_VERSION_V13

    return payload


def generate_methodology_certificate(
    model_data: dict[str, Any],
    decompose_result: dict[str, Any],
    bundle_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Generate a complete Methodology Certificate dict for embedding in bundle.

    This is the top-level entry point. Returns a dict containing:
        - `payload`: the full hash payload (for transparency / embed in report)
        - `hash`: SHA-256 hex of JCS-canonical payload
        - `certificate_version`: "1.3" or "2.0.0"
        - `jcs_available`: bool — True if rfc8785 was used (INV-06 compliance)

    Args:
        model_data: loaded model dict.
        decompose_result: decomposer output dict.
        bundle_manifest: bundle manifest dict.

    Returns:
        {
            "payload": {...},
            "hash": "abc123...",
            "certificate_version": "2.0.0",
            "jcs_available": true
        }
    """
    payload = build_cert_payload(model_data, decompose_result, bundle_manifest)
    cert_hash = compute_cert_hash(payload)
    return {
        'payload': payload,
        'hash': cert_hash,
        'certificate_version': payload.get('certificate_version', CERT_VERSION_V13),
        'jcs_available': _HAS_JCS,
    }
