# AI Agency Test Report

**Date:** 2026-03-22 14:30 МСК  
**Total:** 33 tests | **7 pass** | **26 fail**
**Duration:** 923.9s

---

## Integration Tests — 7/33 pass


### creative-director — 5/6 pass

| Command | Status | Duration | Details |
|---------|--------|----------|---------|
| /brand-memory | ✅ | 139.1s | OK (5593 chars, brand OK) |
| /comm-audit | ✅ | 126.5s | OK (6250 chars) |
| /creative | ✅ | 80.5s | OK: 5 concepts, frameworks detected |
| /ad-variants | ✅ | 11.2s | OK: 4 variants, 1 hook types |
| | ⚠️ | | Only 4 variants (expected 10+) |
| | ⚠️ | | Only 1 hook types detected (expected 3+) |
| /focus-group | ❌ | 10.8s | 0 markers (HIGH:0 MED:0 LOW:0 VAL:0); MISSING limitations disclaimer; need >= 3 |
| | ⚠️ | | No markdown table found (expected AIDA scoring) |
| | ⚠️ | | No limitations/validation disclaimer found |
| /format-creative | ✅ | 129.9s | OK: 5 formats found |

### communication-strategist — 2/6 pass

| Command | Status | Duration | Details |
|---------|--------|----------|---------|
| /positioning | ✅ | 192.9s | OK (11146 chars, brand OK) |
| /brief | ✅ | 12.2s | OK: 0 sections |
| | ⚠️ | | Only 0 sections (expected 10+) |
| /messages | ❌ | 121.7s | Empty output |
| /comm-audit | ❌ | 3.5s | Empty output |
| /focus-group | ❌ | 3.5s | Empty output |
| /quick-diagnostics | ❌ | 3.6s | Empty output |

### lawyer-contracts — 0/5 pass

| Command | Status | Duration | Details |
|---------|--------|----------|---------|
| /contract | ❌ | 3.5s | Empty output |
| /contract-checklist | ❌ | 4.1s | Empty output |
| /contract-counter | ❌ | 3.8s | Empty output |
| /contract-риски | ❌ | 3.6s | Empty output |
| /contract-услуги | ❌ | 3.6s | Empty output |

### lawyer-claims — 0/4 pass

| Command | Status | Duration | Details |
|---------|--------|----------|---------|
| /pretension-analyze | ❌ | 3.9s | Empty output |
| /pretension-write | ❌ | 3.7s | Empty output |
| /nda-draft | ❌ | 3.7s | Empty output |
| /settlement-plan | ❌ | 3.6s | Empty output |

### lawyer-advertising — 0/4 pass

| Command | Status | Duration | Details |
|---------|--------|----------|---------|
| /qa | ❌ | 3.7s | Empty output |
| /qa-фарма | ❌ | 3.7s | Empty output |
| /qa-финансы | ❌ | 3.7s | Empty output |
| /qa-template | ❌ | 3.6s | Empty output |

### media-analyst — 0/4 pass

| Command | Status | Duration | Details |
|---------|--------|----------|---------|
| /action-title | ❌ | 3.6s | Empty output |
| /executive-summary | ❌ | 3.8s | Empty output |
| /bridges | ❌ | 3.7s | Empty output |
| /analytics | ❌ | 3.5s | Empty output |

### communication-analyst — 0/4 pass

| Command | Status | Duration | Details |
|---------|--------|----------|---------|
| /sentiment | ❌ | 3.6s | Empty output |
| /media-monitor | ❌ | 3.7s | Empty output |
| /crisis-analysis | ❌ | 3.5s | Empty output |
| /effectiveness | ❌ | 14.4s | Empty output |

---

## Failures (26)

- **creative-director** `/focus-group` `focus_group`: 0 markers (HIGH:0 MED:0 LOW:0 VAL:0); MISSING limitations disclaimer; need >= 3
- **communication-strategist** `/messages` `messages`: Empty output
- **communication-strategist** `/comm-audit` `comm_audit`: Empty output
- **communication-strategist** `/focus-group` `focus_group`: Empty output
- **communication-strategist** `/quick-diagnostics` `quick_diagnostics`: Empty output
- **lawyer-contracts** `/contract` `contract`: Empty output
- **lawyer-contracts** `/contract-checklist` `contract_checklist`: Empty output
- **lawyer-contracts** `/contract-counter` `contract_counter`: Empty output
- **lawyer-contracts** `/contract-риски` `contract_risks`: Empty output
- **lawyer-contracts** `/contract-услуги` `contract_template`: Empty output
- **lawyer-claims** `/pretension-analyze` `pretension_analyze`: Empty output
- **lawyer-claims** `/pretension-write` `pretension_write`: Empty output
- **lawyer-claims** `/nda-draft` `nda_draft`: Empty output
- **lawyer-claims** `/settlement-plan` `settlement_plan`: Empty output
- **lawyer-advertising** `/qa` `qa`: Empty output
- **lawyer-advertising** `/qa-фарма` `qa_pharma`: Empty output
- **lawyer-advertising** `/qa-финансы` `qa_finance`: Empty output
- **lawyer-advertising** `/qa-template` `qa_template`: Empty output
- **media-analyst** `/action-title` `action_title`: Empty output
- **media-analyst** `/executive-summary` `executive_summary`: Empty output
- **media-analyst** `/bridges` `bridges`: Empty output
- **media-analyst** `/analytics` `analytics`: Empty output
- **communication-analyst** `/sentiment` `sentiment`: Empty output
- **communication-analyst** `/media-monitor` `media_monitor`: Empty output
- **communication-analyst** `/crisis-analysis` `crisis_analysis`: Empty output
- **communication-analyst** `/effectiveness` `effectiveness`: Empty output