"""
ACE-KG evaluation — measures two dimensions:

  1. Email category classification accuracy
     Tier-1 keyword classifier tested against a 24-message synthetic corpus
     (6 per category: obligation, opportunity, rewards, social).

  2. SHACL conformance validation latency
     30 ACE-KG messages (20 conforming, 10 deliberately non-conforming)
     validated against ace/ace_shacl_shapes.ttl with pyshacl 0.31.0.
     Reports mean latency, standard deviation, and violation-detection rate.

Run from the repository root:
    python eval/ace_eval.py

Requires: pip install pyshacl rdflib
Results saved to ace_eval_results.json.
"""

import json
import pathlib
import statistics
import time
from typing import Literal

# ─── Paths ────────────────────────────────────────────────────────────────────

ROOT = pathlib.Path(__file__).parent.parent
SHAPES_PATH = ROOT / "ace" / "ace_shacl_shapes.ttl"
RESULTS_PATH = pathlib.Path(__file__).parent / "ace_eval_results.json"

# ══════════════════════════════════════════════════════════════════════════════
# PART 1 — EMAIL CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

# Keyword sets mirror the Tier-1 path in email_parser.py.
# Tier-2 (Gemini) is invoked only for zero-match fallback; not benchmarked here.

_OBLIGATION_KEYWORDS = {
    "renew", "renewal", "expires", "expiring", "deadline", "due date",
    "overdue", "schedule", "appointment", "refill", "policy", "premium",
    "registration", "license", "permit", "tax", "return by", "pick up by",
}
_OPPORTUNITY_KEYWORDS = {
    "sale", "% off", "limited time", "flash", "exclusive", "clearance",
    "promo code", "offer expires", "weekend deal", "discount", "save up to",
    "special offer", "deal", "coupon",
}
_REWARDS_KEYWORDS = {
    "points", "miles", "cashback", "rewards", "tier", "expire",
    "redeem", "loyalty", "your balance", "earn points", "points expiring",
    "stars", "credits", "reward balance",
}
_SOCIAL_KEYWORDS = {
    "follower", "connection request", "community update", "mention",
    "started following", "liked your", "anniversary", "new message",
    "joined your", "endorsed you",
}

Category = Literal["obligation", "opportunity", "rewards", "social"]


def classify_email(subject: str, body: str) -> Category:
    """Tier-1 keyword classifier — O(|keywords|) per call."""
    text = (subject + " " + body).lower()
    scores: dict[Category, int] = {
        "obligation":  sum(1 for kw in _OBLIGATION_KEYWORDS  if kw in text),
        "opportunity": sum(1 for kw in _OPPORTUNITY_KEYWORDS if kw in text),
        "rewards":     sum(1 for kw in _REWARDS_KEYWORDS     if kw in text),
        "social":      sum(1 for kw in _SOCIAL_KEYWORDS      if kw in text),
    }
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return best if scores[best] > 0 else "obligation"  # obligation = default


# Synthetic corpus: (subject, body, expected_category)
# 6 messages per category; edge cases noted inline.
CORPUS: list[tuple[str, str, Category]] = [
    # ── Obligations ───────────────────────────────────────────────────────────
    (
        "Your auto insurance renews April 15",
        "Your State Farm policy POL-98234 renews on April 15 2026. "
        "Review your coverage and update payment details.",
        "obligation",
    ),
    (
        "Prescription refill due in 5 days",
        "Your Lisinopril 10 mg has 4 days supply remaining. "
        "Refill before March 12 to avoid a gap in therapy.",
        "obligation",
    ),
    (
        "Vehicle registration expires March 31",
        "Your vehicle registration expires March 31 2026. "
        "Renew your license plate at the DMV or online.",
        "obligation",
    ),
    (
        "Tax return deadline: April 15",
        "File your 2025 federal tax return by April 15 to avoid penalties. "
        "Schedule time to review your documents.",
        "obligation",
    ),
    (
        "Schedule your annual wellness visit",
        "You are due for your annual wellness appointment. "
        "Schedule before June 30 to use your 2026 benefits.",
        "obligation",
    ),
    (
        "Return deadline: 30 days remaining",
        "Your return window for order #12345 closes March 20. "
        "Return by that date for a full refund.",
        "obligation",
    ),
    # ── Commercial opportunities ───────────────────────────────────────────────
    (
        "Flash Sale: 30% off all footwear this weekend",
        "Get 30% off sitewide. Limited time offer expires Sunday March 8.",
        "opportunity",
    ),
    (
        "Exclusive 25% discount — members only",
        "As a valued member, enjoy an exclusive 25% discount this week. "
        "Coupon applied at checkout.",
        "opportunity",
    ),
    (
        "Weekend deal: Save up to 40% on electronics",
        "Save up to 40% on select electronics. Weekend deal ends Sunday.",
        "opportunity",
    ),
    (
        "Clearance sale — promo code SAVE20",
        "Use promo code SAVE20 at checkout for 20% off clearance items.",
        "opportunity",
    ),
    (
        "Limited time: buy one get one free",
        "Our BOGO sale offer expires tonight. Limited time — shop now.",
        "opportunity",
    ),
    (
        "Special offer: 15% off your next order",
        "We have a special offer just for you. 15% off coupon inside.",
        "opportunity",
    ),
    # ── Rewards signals ────────────────────────────────────────────────────────
    (
        "Your 200 Stars expire March 15",
        "Redeem your 200 Stars ($8.00 value) before March 15 or they expire.",
        "rewards",
    ),
    (
        "You have 2 400 miles ready to redeem",
        "Your rewards balance: 2 400 miles. Redeem before they expire June 1.",
        "rewards",
    ),
    (
        "Tier upgrade: You have reached Gold status",
        "Congratulations! Your loyalty tier is now Gold. Enjoy new benefits.",
        "rewards",
    ),
    (
        "Your cashback reward balance: $12.50",
        "You have $12.50 in cashback rewards. Redeem your reward balance now.",
        "rewards",
    ),
    (
        "Earn triple points this weekend",
        "Your current balance: 1 800 points. Earn bonus points on all purchases.",
        "rewards",
    ),
    (
        "Points expiring soon — do not lose them",
        "You have 500 loyalty points expiring March 20. Redeem before they expire.",
        "rewards",
    ),
    # ── Social / platform updates ──────────────────────────────────────────────
    (
        "Alex Chen started following you",
        "Alex Chen started following you on LinkedIn. View their profile.",
        "social",
    ),
    (
        "You have a new connection request",
        "Sarah Johnson sent you a connection request on LinkedIn.",
        "social",
    ),
    (
        "Your post was liked by 15 people",
        "15 people liked your recent update. View the engagement.",
        "social",
    ),
    (
        "Community update: New discussion in your group",
        "A community update is available: new discussion in Flutter Developers.",
        "social",
    ),
    (
        "Work anniversary: 2 years at Acme Corp",
        "Congratulate your connection on their work anniversary. "
        "2 years at Acme Corp — send a note.",
        "social",
    ),
    (
        "Someone mentioned you in a comment",
        "You have a new mention in a comment thread. View the conversation.",
        "social",
    ),
]


def run_classification_eval() -> dict:
    cats: list[Category] = ["obligation", "opportunity", "rewards", "social"]
    per_cat: dict[str, dict] = {c: {"correct": 0, "total": 0} for c in cats}

    for subject, body, expected in CORPUS:
        predicted = classify_email(subject, body)
        per_cat[expected]["total"] += 1
        if predicted == expected:
            per_cat[expected]["correct"] += 1

    total_correct = sum(v["correct"] for v in per_cat.values())
    total_msgs    = len(CORPUS)

    return {
        "total": total_msgs,
        "correct": total_correct,
        "accuracy": round(100.0 * total_correct / total_msgs, 1),
        "per_category": {
            c: {
                "correct": v["correct"],
                "total":   v["total"],
                "accuracy": round(100.0 * v["correct"] / v["total"], 1),
            }
            for c, v in per_cat.items()
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# PART 2 — SHACL VALIDATION LATENCY
# ══════════════════════════════════════════════════════════════════════════════

try:
    import pyshacl
    from rdflib import Graph
    PYSHACL_AVAILABLE = True
except ImportError:
    PYSHACL_AVAILABLE = False

PREFIXES = """
@prefix ace:    <https://ace-protocol.org/kg/v1/> .
@prefix schema: <https://schema.org/> .
@prefix prov:   <http://www.w3.org/ns/prov#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
"""

# 30 test instances: (turtle_fragment, expected_conforms: bool, label)
# 20 conforming (5 per category) + 10 non-conforming (2–3 per category).

SHACL_CASES: list[tuple[str, bool, str]] = [

    # ── TemporalObligation — 5 conforming ─────────────────────────────────────
    ("""<urn:ace:obl-001> a ace:ACEMessage, ace:TemporalObligation ;
        prov:generatedAtTime "2026-03-08T10:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "State Farm" ] ;
        ace:deadline "2026-04-15"^^xsd:date ;
        ace:optimalWindowStart 45 ;
        ace:optimalWindowEnd   14 ;
        ace:urgencyClass ace:FIRM .""",
     True, "Obligation-OK: insurance renewal"),

    ("""<urn:ace:obl-002> a ace:ACEMessage, ace:TemporalObligation ;
        prov:generatedAtTime "2026-03-08T09:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "CVS Pharmacy" ] ;
        ace:deadline "2026-03-12"^^xsd:date ;
        ace:optimalWindowStart 14 ;
        ace:optimalWindowEnd    3 ;
        ace:urgencyClass ace:HARD .""",
     True, "Obligation-OK: prescription refill"),

    ("""<urn:ace:obl-003> a ace:ACEMessage, ace:TemporalObligation ;
        prov:generatedAtTime "2026-03-08T08:30:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "IRS" ] ;
        ace:deadline "2026-04-15"^^xsd:date ;
        ace:optimalWindowStart 45 ;
        ace:optimalWindowEnd    7 ;
        ace:urgencyClass ace:FIRM .""",
     True, "Obligation-OK: tax deadline"),

    ("""<urn:ace:obl-004> a ace:ACEMessage, ace:TemporalObligation ;
        prov:generatedAtTime "2026-03-08T11:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "DMV" ] ;
        ace:deadline "2026-03-31"^^xsd:date ;
        ace:optimalWindowStart 21 ;
        ace:optimalWindowEnd    5 ;
        ace:urgencyClass ace:SOFT .""",
     True, "Obligation-OK: vehicle registration"),

    ("""<urn:ace:obl-005> a ace:ACEMessage, ace:TemporalObligation ;
        prov:generatedAtTime "2026-03-08T14:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Target" ] ;
        ace:deadline "2026-03-20"^^xsd:date ;
        ace:optimalWindowStart 21 ;
        ace:optimalWindowEnd    2 ;
        ace:urgencyClass ace:HARD .""",
     True, "Obligation-OK: return deadline"),

    # ── TemporalObligation — 3 non-conforming ─────────────────────────────────
    ("""<urn:ace:obl-bad-001> a ace:ACEMessage, ace:TemporalObligation ;
        prov:generatedAtTime "2026-03-08T10:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "State Farm" ] ;
        ace:optimalWindowStart 45 ;
        ace:optimalWindowEnd   14 ;
        ace:urgencyClass ace:FIRM .""",
     False, "Obligation-FAIL: missing ace:deadline"),

    ("""<urn:ace:obl-bad-002> a ace:ACEMessage, ace:TemporalObligation ;
        prov:generatedAtTime "2026-03-08T10:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "IRS" ] ;
        ace:deadline "2026-04-15"^^xsd:date ;
        ace:optimalWindowStart 45 ;
        ace:optimalWindowEnd   7 ;
        ace:urgencyClass ace:URGENT .""",
     False, "Obligation-FAIL: invalid urgencyClass 'URGENT'"),

    ("""<urn:ace:obl-bad-003> a ace:ACEMessage, ace:TemporalObligation ;
        prov:generatedAtTime "2026-03-08T10:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "DMV" ] ;
        ace:deadline "2026-03-31"^^xsd:date ;
        ace:optimalWindowStart 21 ;
        ace:optimalWindowEnd   -5 ;
        ace:urgencyClass ace:SOFT .""",
     False, "Obligation-FAIL: optimalWindowEnd = -5 (< 0)"),

    # ── CommercialOpportunity — 5 conforming ──────────────────────────────────
    ("""<urn:ace:opp-001> a ace:ACEMessage, ace:CommercialOpportunity ;
        prov:generatedAtTime "2026-03-08T07:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Nike" ] ;
        ace:offerValidUntil "2026-03-10T23:59:00Z"^^xsd:dateTime ;
        ace:discountPercent 30.0 .""",
     True, "Opportunity-OK: Nike flash sale 30%"),

    ("""<urn:ace:opp-002> a ace:ACEMessage, ace:CommercialOpportunity ;
        prov:generatedAtTime "2026-03-08T08:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Best Buy" ] ;
        ace:offerValidUntil "2026-03-09T23:59:00Z"^^xsd:dateTime ;
        ace:discountPercent 40.0 .""",
     True, "Opportunity-OK: electronics 40%"),

    ("""<urn:ace:opp-003> a ace:ACEMessage, ace:CommercialOpportunity ;
        prov:generatedAtTime "2026-03-08T09:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Gap" ] ;
        ace:offerValidUntil "2026-03-15T23:59:00Z"^^xsd:dateTime ;
        ace:discountPercent 25.0 .""",
     True, "Opportunity-OK: exclusive member discount"),

    ("""<urn:ace:opp-004> a ace:ACEMessage, ace:CommercialOpportunity ;
        prov:generatedAtTime "2026-03-08T10:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Amazon" ] ;
        ace:offerValidUntil "2026-03-08T23:59:00Z"^^xsd:dateTime .""",
     True, "Opportunity-OK: BOGO (no discountPercent)"),

    ("""<urn:ace:opp-005> a ace:ACEMessage, ace:CommercialOpportunity ;
        prov:generatedAtTime "2026-03-08T11:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Macy's" ] ;
        ace:offerValidUntil "2026-03-20T23:59:00Z"^^xsd:dateTime ;
        ace:discountPercent 15.0 .""",
     True, "Opportunity-OK: 15% membership offer"),

    # ── CommercialOpportunity — 2 non-conforming ──────────────────────────────
    ("""<urn:ace:opp-bad-001> a ace:ACEMessage, ace:CommercialOpportunity ;
        prov:generatedAtTime "2026-03-08T07:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Nike" ] ;
        ace:discountPercent 30.0 .""",
     False, "Opportunity-FAIL: missing ace:offerValidUntil"),

    ("""<urn:ace:opp-bad-002> a ace:ACEMessage, ace:CommercialOpportunity ;
        prov:generatedAtTime "2026-03-08T08:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Sketchy Store" ] ;
        ace:offerValidUntil "2026-03-09T23:59:00Z"^^xsd:dateTime ;
        ace:discountPercent 150.0 .""",
     False, "Opportunity-FAIL: discountPercent = 150 (> 100)"),

    # ── RewardsSignal — 5 conforming ──────────────────────────────────────────
    ("""<urn:ace:rew-001> a ace:ACEMessage, ace:RewardsSignal ;
        prov:generatedAtTime "2026-03-08T08:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Starbucks" ] ;
        ace:loyaltyProgramName "Starbucks Rewards" ;
        ace:pointsBalance 200 ;
        ace:redeemableValue 8.00 ;
        ace:pointsExpiry "2026-03-15T00:00:00Z"^^xsd:dateTime .""",
     True, "Rewards-OK: Starbucks Stars with expiry"),

    ("""<urn:ace:rew-002> a ace:ACEMessage, ace:RewardsSignal ;
        prov:generatedAtTime "2026-03-08T09:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Delta Air Lines" ] ;
        ace:loyaltyProgramName "SkyMiles" ;
        ace:pointsBalance 2400 ;
        ace:redeemableValue 24.00 ;
        ace:pointsExpiry "2026-06-01T00:00:00Z"^^xsd:dateTime .""",
     True, "Rewards-OK: Delta miles with expiry"),

    ("""<urn:ace:rew-003> a ace:ACEMessage, ace:RewardsSignal ;
        prov:generatedAtTime "2026-03-08T10:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Chase" ] ;
        ace:loyaltyProgramName "Chase Sapphire Rewards" ;
        ace:pointsBalance 8500 ;
        ace:redeemableValue 85.00 .""",
     True, "Rewards-OK: Chase cashback (no expiry)"),

    ("""<urn:ace:rew-004> a ace:ACEMessage, ace:RewardsSignal ;
        prov:generatedAtTime "2026-03-08T11:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Marriott" ] ;
        ace:loyaltyProgramName "Marriott Bonvoy" ;
        ace:pointsBalance 45000 ;
        ace:tierStatus "Gold Elite" .""",
     True, "Rewards-OK: Marriott tier upgrade (no value)"),

    ("""<urn:ace:rew-005> a ace:ACEMessage, ace:RewardsSignal ;
        prov:generatedAtTime "2026-03-08T12:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Target Circle" ] ;
        ace:loyaltyProgramName "Target Circle" ;
        ace:pointsBalance 500 ;
        ace:pointsExpiry "2026-03-20T00:00:00Z"^^xsd:dateTime .""",
     True, "Rewards-OK: Target Circle points expiring"),

    # ── RewardsSignal — 2 non-conforming ──────────────────────────────────────
    ("""<urn:ace:rew-bad-001> a ace:ACEMessage, ace:RewardsSignal ;
        prov:generatedAtTime "2026-03-08T08:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Starbucks" ] ;
        ace:pointsBalance 200 ;
        ace:redeemableValue 8.00 .""",
     False, "Rewards-FAIL: missing ace:loyaltyProgramName"),

    ("""<urn:ace:rew-bad-002> a ace:ACEMessage, ace:RewardsSignal ;
        prov:generatedAtTime "2026-03-08T09:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "AirMiles" ] ;
        ace:loyaltyProgramName "AirMiles" ;
        ace:pointsBalance -100 .""",
     False, "Rewards-FAIL: pointsBalance = -100 (< 0)"),

    # ── SocialUpdate — 5 conforming ────────────────────────────────────────────
    ("""<urn:ace:soc-001> a ace:ACEMessage, ace:SocialUpdate ;
        prov:generatedAtTime "2026-03-08T07:30:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "LinkedIn" ] ;
        ace:agentValueSignal 0.3 .""",
     True, "Social-OK: connection request (0.3)"),

    ("""<urn:ace:soc-002> a ace:ACEMessage, ace:SocialUpdate ;
        prov:generatedAtTime "2026-03-08T08:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Twitter" ] ;
        ace:agentValueSignal 0.1 .""",
     True, "Social-OK: post liked (0.1)"),

    ("""<urn:ace:soc-003> a ace:ACEMessage, ace:SocialUpdate ;
        prov:generatedAtTime "2026-03-08T09:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "LinkedIn" ] ;
        ace:agentValueSignal 0.2 .""",
     True, "Social-OK: work anniversary (0.2)"),

    ("""<urn:ace:soc-004> a ace:ACEMessage, ace:SocialUpdate ;
        prov:generatedAtTime "2026-03-08T10:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Reddit" ] ;
        ace:agentValueSignal 0.4 .""",
     True, "Social-OK: mention (0.4)"),

    ("""<urn:ace:soc-005> a ace:ACEMessage, ace:SocialUpdate ;
        prov:generatedAtTime "2026-03-08T11:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Instagram" ] ;
        ace:agentValueSignal 0.15 .""",
     True, "Social-OK: new follower (0.15)"),

    # ── SocialUpdate — 3 non-conforming ───────────────────────────────────────
    ("""<urn:ace:soc-bad-001> a ace:ACEMessage, ace:SocialUpdate ;
        prov:generatedAtTime "2026-03-08T07:30:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "LinkedIn" ] .""",
     False, "Social-FAIL: missing ace:agentValueSignal"),

    ("""<urn:ace:soc-bad-002> a ace:ACEMessage, ace:SocialUpdate ;
        prov:generatedAtTime "2026-03-08T08:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Twitter" ] ;
        ace:agentValueSignal 1.5 .""",
     False, "Social-FAIL: agentValueSignal = 1.5 (> 1.0)"),

    ("""<urn:ace:soc-bad-003> a ace:ACEMessage, ace:SocialUpdate ;
        prov:generatedAtTime "2026-03-08T09:00:00Z"^^xsd:dateTime ;
        ace:counterparty [ a schema:Organization ; schema:name "Reddit" ] ;
        ace:agentValueSignal "high"^^xsd:string .""",
     False, "Social-FAIL: agentValueSignal has wrong datatype (xsd:string)"),
]


def run_shacl_eval() -> dict:
    if not PYSHACL_AVAILABLE:
        return {"error": "pyshacl not installed — run: pip install pyshacl rdflib"}

    shapes_graph = Graph()
    shapes_graph.parse(str(SHAPES_PATH), format="turtle")

    # Warm-up: one dummy validation to avoid cold-start JIT overhead in measurements
    _warmup_ttl = PREFIXES + SHACL_CASES[0][0]
    _wg = Graph()
    _wg.parse(data=_warmup_ttl, format="turtle")
    pyshacl.validate(_wg, shacl_graph=shapes_graph, abort_on_first=False)

    records: list[dict] = []
    for turtle_fragment, expected_conforms, label in SHACL_CASES:
        full_ttl = PREFIXES + turtle_fragment
        data_graph = Graph()
        data_graph.parse(data=full_ttl, format="turtle")

        t0 = time.perf_counter()
        conforms, _, _ = pyshacl.validate(
            data_graph,
            shacl_graph=shapes_graph,
            abort_on_first=False,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        detection_correct = (conforms == expected_conforms)
        records.append({
            "label": label,
            "expected_conforms": expected_conforms,
            "actual_conforms": conforms,
            "detection_correct": detection_correct,
            "latency_ms": round(elapsed_ms, 3),
        })

    # Aggregate statistics
    all_latencies   = [r["latency_ms"] for r in records]
    conf_latencies  = [r["latency_ms"] for r in records if r["expected_conforms"]]
    nonconf_latencies = [r["latency_ms"] for r in records if not r["expected_conforms"]]
    detection_rate  = sum(1 for r in records if r["detection_correct"]) / len(records)

    def _stats(lats: list[float]) -> dict:
        if not lats:
            return {}
        return {
            "n":      len(lats),
            "mean":   round(statistics.mean(lats), 2),
            "sd":     round(statistics.stdev(lats), 2) if len(lats) > 1 else 0.0,
            "min":    round(min(lats), 2),
            "max":    round(max(lats), 2),
        }

    return {
        "n_total":            len(records),
        "n_conforming":       sum(1 for r in records if r["expected_conforms"]),
        "n_nonconforming":    sum(1 for r in records if not r["expected_conforms"]),
        "detection_rate":     round(detection_rate * 100, 1),
        "latency_all_ms":     _stats(all_latencies),
        "latency_conforming_ms":    _stats(conf_latencies),
        "latency_nonconforming_ms": _stats(nonconf_latencies),
        "records": records,
    }


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 68)
    print("ACE-KG Evaluation")
    print("=" * 68)

    # ── Part 1: Classification ─────────────────────────────────────────────────
    print("\n── Part 1: Email category classification ──")
    cls = run_classification_eval()
    print(f"\n{'Category':<14} {'Correct':>8} {'Total':>7} {'Accuracy':>10}")
    print("-" * 44)
    for cat, v in cls["per_category"].items():
        print(f"{cat:<14} {v['correct']:>8} {v['total']:>7} {v['accuracy']:>9.1f}%")
    print("-" * 44)
    print(f"{'Overall':<14} {cls['correct']:>8} {cls['total']:>7} {cls['accuracy']:>9.1f}%")

    # ── Part 2: SHACL validation ───────────────────────────────────────────────
    print("\n── Part 2: SHACL validation latency ──")
    shacl = run_shacl_eval()

    if "error" in shacl:
        print(f"\n  {shacl['error']}")
    else:
        print(f"\n  Messages validated  : {shacl['n_total']} "
              f"({shacl['n_conforming']} conforming, "
              f"{shacl['n_nonconforming']} non-conforming)")
        print(f"  Detection accuracy  : {shacl['detection_rate']}%")
        s = shacl["latency_all_ms"]
        print(f"  Latency (all)       : {s['mean']} ± {s['sd']} ms  "
              f"[{s['min']}–{s['max']} ms]")
        sc = shacl["latency_conforming_ms"]
        print(f"  Latency (conforming): {sc['mean']} ± {sc['sd']} ms")
        sn = shacl["latency_nonconforming_ms"]
        print(f"  Latency (violation) : {sn['mean']} ± {sn['sd']} ms")

        print(f"\n  {'Label':<50} {'Conforms':>8} {'ms':>8}")
        print("  " + "-" * 70)
        for r in shacl["records"]:
            tick = "✓" if r["detection_correct"] else "✗"
            print(f"  {tick} {r['label']:<49} "
                  f"{'yes' if r['actual_conforms'] else 'no':>8} "
                  f"{r['latency_ms']:>7.1f}")

    # ── Save results ───────────────────────────────────────────────────────────
    results = {"classification": cls, "shacl": shacl}
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results saved to {RESULTS_PATH}")
