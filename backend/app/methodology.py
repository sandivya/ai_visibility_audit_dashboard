import hashlib
import json
from typing import Literal

EvidenceKind = Literal["pages", "prompts"]

SIMULATED_AUDIT_METHODOLOGY_VERSION = "simulated-v2"
SIMULATED_AUDIT_DISCLOSURE = (
    "Demo data only: no live AI provider or crawler is queried. Results are stable for this "
    "methodology version, brand, domain, and competitor set; changing those inputs can change "
    "the output."
)
SIMULATED_AUDIT_SCORING_SUMMARY = (
    "The 100-point score uses a 20-point baseline, up to 50 points for prompt mentions, "
    "15 for healthy page responses, 10 for descriptive titles, and 5 for prompts without "
    "tracked competitors."
)
SIMULATED_AUDIT_STABLE_INPUTS = ("brand", "domain", "competitor set")


def canonical_competitor_set(competitors: list[str]) -> list[str]:
    return sorted({item.strip().casefold() for item in competitors})


def simulated_configuration_digest(*, brand: str, domain: str, competitors: list[str]) -> bytes:
    """Return a versioned, order-independent fingerprint for simulated evidence."""
    payload = {
        "brand": brand.strip().casefold(),
        "competitors": canonical_competitor_set(competitors),
        "domain": domain.strip().casefold(),
        "methodology_version": SIMULATED_AUDIT_METHODOLOGY_VERSION,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).digest()


def evidence_kind_for_finding(category: str) -> EvidenceKind:
    return "pages" if category.casefold() == "technical_seo" else "prompts"


# The deterministic demo creates one recommendation for each named finding. Keeping the
# relationship in one place lets API clients navigate to supporting evidence without relying on
# array order or duplicating title rules in the frontend.
RECOMMENDATION_RELATIONSHIPS: dict[str, tuple[str, EvidenceKind]] = {
    "Publish comparison-led content": ("Brand missing from a high-intent prompt", "prompts"),
    "Improve product metadata": ("Product page title lacks context", "pages"),
    "Strengthen trusted-brand signals": ("Brand absent from a trust-focused prompt", "prompts"),
    "Clarify competitive differentiation": (
        "Competitor surfaced in a trust-focused prompt",
        "prompts",
    ),
    "Expand third-party proof and citations": (
        "Visibility relies on limited supporting proof",
        "prompts",
    ),
}


def related_finding_title(recommendation_title: str) -> str | None:
    relationship = RECOMMENDATION_RELATIONSHIPS.get(recommendation_title)
    return relationship[0] if relationship else None


def evidence_kind_for_recommendation(recommendation_title: str) -> EvidenceKind:
    relationship = RECOMMENDATION_RELATIONSHIPS.get(recommendation_title)
    return relationship[1] if relationship else "prompts"
