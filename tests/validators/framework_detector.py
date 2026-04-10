"""
Framework detection in Claude output.
Checks that the AI applied expected methodological frameworks.
"""
import re
from dataclasses import dataclass, field


@dataclass
class FrameworkResult:
    framework: str
    found: bool
    matched_pattern: str = ""


# Framework patterns per cabinet
CABINET_FRAMEWORKS: dict[str, dict[str, list[str]]] = {
    "creative-director": {
        "Score_HumanKind": [r"Score\s*[:=\(]?\s*\d", r"HumanKind\s*[:=\(]?\s*\d"],
        "AIDA": [r"\bAIDA\b", r"Attention.*Interest.*Desire.*Action"],
        "ELM": [r"\bELM\b", r"Elaboration Likelihood", r"central route", r"peripheral route"],
        "Attention_Economics": [r"0[-–]3\s*сек", r"\bHook\b.*скролл", r"HOOK.*TENSION.*PAYOFF"],
        "Method_used": [r"\bSIT\b", r"\bTRIZ\b", r"\bSCAMPER\b", r"Bisociation", r"Synectics"],
    },
    "communication-strategist": {
        "Ehrenberg_Bass": [r"Ehrenberg.?Bass", r"Category Entry Points?", r"\bCEP\b"],
        "PG_Positioning": [r"Для\s+.{1,50},\s+которая", r"Positioning Statement", r"формула P&G"],
        "Binet_Field": [r"Binet.*Field", r"60.?40", r"brand building.*performance"],
        "JTBD": [r"\bJTBD\b", r"Job.to.be.Done", r"функциональная работа"],
        "CEP_coverage": [r"Category Entry Points?", r"\bCEP\b", r"Mental Availability"],
    },
    "lawyer-contracts": {
        "IACCM": [r"\bIACCM\b", r"Top Negotiated Terms?", r"наиболее оспариваемых"],
        "Risk_Quantification": [r"Severity.*Probability", r"Risk\s+Score", r"Risk\s+Heatmap"],
        "Red_Flags": [r"Red\s+Flags?", r"красн[ыйые]+\s+флаг", r"безлимитн"],
        "GK_references": [r"ст\.\s*\d+\s*ГК", r"Гражданского кодекса", r"ст\.\s*\d+\s*АПК"],
        "BATNA": [r"\bBATNA\b", r"\bZOPA\b", r"переговорная позиция"],
    },
    "lawyer-claims": {
        "IRAC": [r"\bIRAC\b", r"Issue.*Rule.*Application.*Conclusion", r"применение нормы"],
        "Decision_Tree": [r"Decision Tree", r"дерево решений", r"сценари[йи] \d"],
        "Plenum_refs": [r"Пленум", r"ВС РФ", r"ВАС РФ", r"Постановлени[ея].*Пленум"],
        "Art_333": [r"ст\.\s*333", r"снижение неустойки", r"статья 333"],
        "BATNA_claims": [r"\bBATNA\b", r"лучшая альтернатива", r"Timeline Risk"],
    },
    "lawyer-advertising": {
        "FZ_38": [r"38-ФЗ", r"Закон о рекламе", r"«О рекламе»"],
        "ORD_erid": [r"\bОРД\b", r"\berid\b", r"маркировка рекламы", r"ЕРИР"],
        "KoAP": [r"14\.3\s+КоАП", r"КоАП\s+РФ", r"административн"],
        "Financial_Risk": [r"Financial Risk Score", r"финансовый риск", r"штраф.*руб"],
        "Compliance_Report": [r"Compliance Report", r"статус.*ГОТОВО", r"статус.*ТРЕБУЕТ"],
    },
    "media-analyst": {
        "Action_Title_formula": [r"ЧТО\s*\+\s*КУДА", r"Action Title", r"Insight.First"],
        "Pyramid_Minto": [r"Pyramid Principle", r"Минто", r"Minto"],
        "Data_verification": [r"верификац", r"перепровер", r"сверить с"],
        "Tier1_standard": [r"Tier.1", r"McKinsey", r"BCG"],
        "SO_WHAT": [r"SO WHAT", r"так что", r"что это значит"],
    },
    "communication-analyst": {
        "AMEC": [r"\bAMEC\b", r"Barcelona Principles?"],
        "PESO": [r"\bPESO\b", r"Paid.*Earned.*Shared.*Owned"],
        "No_AVE": [r"AVE.*не валидн", r"AVE.*не рекоменд", r"отказ от AVE"],
        "Sentiment_sophistication": [r"Intensity\s+Score", r"Aspect.Based", r"Emotion Detection"],
        "AMEC_chain": [r"Output.*Outtake.*Outcome", r"Output.*Impact"],
    },
}


def detect_frameworks(text: str, cabinet_id: str) -> list[FrameworkResult]:
    """Detect which frameworks are present in output for a given cabinet."""
    frameworks = CABINET_FRAMEWORKS.get(cabinet_id, {})
    results = []
    for framework_name, patterns in frameworks.items():
        found = False
        matched = ""
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                found = True
                matched = pattern
                break
        results.append(FrameworkResult(
            framework=framework_name,
            found=found,
            matched_pattern=matched,
        ))
    return results


def framework_summary(results: list[FrameworkResult]) -> tuple[int, int, list[str]]:
    """Returns (found_count, total_count, missing_names)."""
    found = sum(1 for r in results if r.found)
    missing = [r.framework for r in results if not r.found]
    return found, len(results), missing
