"""Priority cascade: id -> rule -> fuzzy score -> LLM suggestion -> human decision.

Only id, rule, and human decisions resolve records. Fuzzy scoring finds the likely
partner of an open record and measures what differs, so the case stays open as
evidence for the diagnosis and upgrader agents; the LLM may only suggest. Every
settlement is matched at most once, and the deterministic matcher stays the
authority for backtesting.

Every stage reads the active Policy: id and rule match with its approved
tolerances, fees, and settlement windows; fuzzy compares amounts after approved
fees and takes its thresholds from reference_matching and amount_matching; the
LLM's confidence floor is escalation.confidence_min.
"""
import json
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from pydantic import ValidationError

from app.schemas import MatchSuggestion, Policy
from app.tools.business import (expected_settlement_amounts, local_settlement_date, make_match_decision,
                                normalize_reference)
from app.tools.matcher import BREAK_REASONS, deduplicate, evidence_item, match

HARD_FIELDS = ("customer_id", "currency", "merchant_id", "processor")
HIGH_VALUE_CENTS = 1_000_000
# Matches the largest settlement window a policy may approve.
FUZZY_DATE_SCALE_DAYS = 5
LLM_MAX_CANDIDATES = 5


def _pair(row, other, method, confidence):
    return {"internal_record_id": row["internal_record_id"],
            "processor_record_id": other["processor_record_id"],
            "method": method, "confidence": confidence}


def _claim(proposals):
    """Keep proposals whose settlement is claimed by exactly one ledger row."""
    counts = Counter(p["processor_record_id"] for p in proposals)
    return [p for p in proposals if counts[p["processor_record_id"]] == 1]


def _split(internal, matches):
    matched = {m["internal_record_id"] for m in matches}
    return {"matches": matches, "unmatched": [r for r in internal if r["internal_record_id"] not in matched]}


def _hard_key(row):
    return tuple(row[field] for field in HARD_FIELDS)


def fee_adjusted_delta(row, other, rules):
    """Settlement minus the closest amount the approved fee rules expect."""
    expected = min(expected_settlement_amounts(row, rules), key=lambda amount: abs(other["amount_cents"] - amount))
    return other["amount_cents"] - expected


def fuzzy_score(row, other, policy: Policy, rules=None):
    """0..1 similarity over the soft fields; hard fields must already be equal.

    Amount closeness is measured after the policy's approved fees, and a gap at
    the policy's maximum tolerance or beyond scores zero.
    """
    rules = rules or policy.matching
    reference = SequenceMatcher(None, normalize_reference(row["reference"]),
                                normalize_reference(other["reference"])).ratio()
    gap, cap = abs(fee_adjusted_delta(row, other, rules)), policy.amount_matching.maximum_tolerance_cents
    amount = max(0.0, 1 - gap / cap) if cap else float(gap == 0)
    zone = policy.settlement.timezone
    days = abs((local_settlement_date(other["settlement_date"], zone) - local_settlement_date(row["settlement_date"], zone)).days)
    when = max(0.0, 1 - days / FUZZY_DATE_SCALE_DAYS)
    return round(0.5 * reference + 0.3 * amount + 0.2 * when, 4)


def pair_evidence(row, other, rules, score):
    """What differs between a fuzzy pair, in the matcher's evidence shape."""
    checks = make_match_decision(row, other, rules)["checks"]
    return {**evidence_item(row, other, rules, checks), "source": "fuzzy",
            "processor_record_id": other["processor_record_id"], "fuzzy_score": score,
            "fee_adjusted_delta_cents": fee_adjusted_delta(row, other, rules),
            "reference_raw_equal": row["reference"] == other["reference"]}


def _ranked_candidates(internal, settlements, policy: Policy):
    rules = policy.matching
    index = defaultdict(list)
    for other in settlements:
        index[_hard_key(other)].append(other)
    return {row["internal_record_id"]: sorted(((fuzzy_score(row, other, policy, rules), other)
                                               for other in index[_hard_key(row)]),
                                              key=lambda item: item[0], reverse=True)
            for row in internal}


def match_by_id(internal, settlements, policy: Policy) -> dict:
    """Exact, uncleaned reference shared by exactly one settlement, with every fixed check passing."""
    rules = policy.matching
    index = defaultdict(list)
    for other in settlements:
        index[other["reference"]].append(other)
    proposals = []
    for row in internal:
        candidates = index.get(row["reference"], [])
        if len(candidates) == 1:
            other = candidates[0]
            if make_match_decision(row, other, rules)["decision"] == "MATCH":
                proposals.append(_pair(row, other, "id", 1.0))
    return _split(internal, _claim(proposals))


def match_by_rule(internal, settlements, policy: Policy) -> dict:
    """The existing deterministic matcher: cleaned reference plus the seven fixed checks."""
    result = match(internal, settlements, policy.matching)
    matches = [{**m, "method": "rule", "confidence": 1.0} for m in result["auto_matches"]]
    return {**_split(internal, matches), "cases": result["cases"]}


def match_by_fuzzy_score(internal, settlements, policy: Policy) -> dict:
    """Find each open record's likely partner and measure the difference; resolves nothing.

    A pair needs equal hard fields, a score of at least
    reference_matching.minimum_similarity, and a lead of at least
    reference_matching.minimum_candidate_margin over the runner-up. High-value
    records are never paired.
    """
    rules, thresholds = policy.matching, policy.reference_matching
    ranked = _ranked_candidates(internal, settlements, policy)
    pairs = []
    for row in internal:
        candidates = ranked[row["internal_record_id"]]
        if not candidates or row["amount_cents"] >= HIGH_VALUE_CENTS:
            continue
        best, other = candidates[0]
        runner_up = candidates[1][0] if len(candidates) > 1 else 0.0
        if best >= thresholds.minimum_similarity and best - runner_up >= thresholds.minimum_candidate_margin:
            pairs.append({**_pair(row, other, "fuzzy", best), "evidence": pair_evidence(row, other, rules, best)})
    return {"pairs": _claim(pairs)}


def _parse_suggestion(raw, row, allowed):
    try:
        suggestion = MatchSuggestion.model_validate(json.loads(raw) if isinstance(raw, str) else raw)
    except (ValueError, ValidationError):
        return None
    if suggestion.internal_record_id != row["internal_record_id"]:
        return None
    if suggestion.processor_record_id is not None and suggestion.processor_record_id not in allowed:
        return None
    return suggestion


async def match_by_llm(internal, settlements, policy: Policy, reviewer) -> dict:
    """Ask `reviewer` (async payload -> JSON) to pick among top candidates; returns suggestions only.

    Suggestions below escalation.confidence_min are dropped.
    """
    confidence_min = policy.escalation.confidence_min
    ranked = _ranked_candidates(internal, settlements, policy)
    suggestions = []
    for row in internal:
        candidates = ranked[row["internal_record_id"]][:LLM_MAX_CANDIDATES]
        if not candidates:
            continue
        allowed = {other["processor_record_id"] for _, other in candidates}
        payload = {"ledger": row, "candidates": [{**other, "fuzzy_score": score} for score, other in candidates]}
        suggestion = _parse_suggestion(await reviewer(payload), row, allowed)
        if suggestion and suggestion.processor_record_id and suggestion.confidence >= confidence_min:
            suggestions.append({**suggestion.model_dump(), "method": "llm",
                                "candidate_processor_record_ids": sorted(allowed)})
    return {"suggestions": _claim(suggestions)}


def match_by_human(internal, settlements, suggestions, decisions=None) -> dict:
    """Queue every remaining row for review and apply any decisions already made.

    `decisions` maps internal_record_id to the chosen processor_record_id, or to
    None to confirm the row as a genuine break.
    """
    decisions = decisions or {}
    available = {other["processor_record_id"] for other in settlements}
    by_row = {s["internal_record_id"]: s for s in suggestions}
    chosen = Counter(decisions[r["internal_record_id"]] for r in internal
                     if decisions.get(r["internal_record_id"]) is not None)
    matches, confirmed_breaks, pending = [], [], []
    for row in internal:
        record_id = row["internal_record_id"]
        item = {"internal_record_id": record_id, "suggestion": by_row.get(record_id)}
        if record_id not in decisions:
            pending.append(item)
        elif (choice := decisions[record_id]) is None:
            confirmed_breaks.append(record_id)
        elif choice not in available:
            pending.append({**item, "error": "chosen settlement is unknown or already matched"})
        elif chosen[choice] > 1:
            pending.append({**item, "error": "chosen settlement was picked for more than one record"})
        else:
            matches.append({"internal_record_id": record_id, "processor_record_id": choice,
                            "method": "human", "confidence": 1.0})
    return {"matches": matches, "confirmed_breaks": confirmed_breaks, "pending": pending}


def _attach_pair(case, pair):
    """Give the case its fuzzy partner; where the matcher found none, the pair becomes its evidence."""
    case["fuzzy_pair"] = pair["evidence"]
    if not case["evidence"]:
        case["evidence"] = pair["evidence"]
        case["break_type"] = next((reason for key, reason in BREAK_REASONS.items()
                                   if not pair["evidence"]["checks"][key]), case["break_type"])


def _fuzzy_suggestion(pair):
    evidence = pair["evidence"]
    return {"internal_record_id": pair["internal_record_id"], "processor_record_id": pair["processor_record_id"],
            "confidence": pair["confidence"], "method": "fuzzy",
            "reason": f'amount {evidence["fee_adjusted_delta_cents"]:+d}¢ after fees, '
                      f'date {evidence["date_delta_days"]:+d}d, '
                      f'reference {"identical" if evidence["reference_raw_equal"] else "reformatted"}'}


async def run_cascade(internal, settlements, policy: Policy, *, reviewer=None, decisions=None) -> dict:
    """Run the stages in priority order; only id, rule, and human stages consume records.

    The returned `cases` keep the matcher's shape, so `detect_incidents` reads
    fuzzy-paired evidence alongside the matcher's own.
    """
    canonical, duplicates = deduplicate(settlements)
    remaining, pool, matches = internal, canonical, []

    def consume(stage_matches):
        nonlocal pool
        used = {m["processor_record_id"] for m in stage_matches}
        pool = [other for other in pool if other["processor_record_id"] not in used]
        matches.extend(stage_matches)

    by_id = match_by_id(remaining, pool, policy)
    consume(by_id["matches"])
    by_rule = match_by_rule(by_id["unmatched"], pool, policy)
    consume(by_rule["matches"])
    remaining = by_rule["unmatched"]

    pairs = match_by_fuzzy_score(remaining, pool, policy)["pairs"]
    cases = {c["internal_record_id"]: c for c in by_rule["cases"]}
    for pair in pairs:
        _attach_pair(cases[pair["internal_record_id"]], pair)

    paired = {p["internal_record_id"] for p in pairs}
    unpaired = [r for r in remaining if r["internal_record_id"] not in paired]
    llm = (await match_by_llm(unpaired, pool, policy, reviewer))["suggestions"] if reviewer else []

    human = match_by_human(remaining, pool, [_fuzzy_suggestion(p) for p in pairs] + llm, decisions)
    consume(human["matches"])
    resolved = {m["internal_record_id"] for m in human["matches"]} | set(human["confirmed_breaks"])
    for record_id in human["confirmed_breaks"]:
        cases[record_id]["status"] = "CONFIRMED_BREAK"
    return {"matches": matches, "cases": [c for c in cases.values() if c["internal_record_id"] not in resolved],
            "pending_review": human["pending"], "confirmed_breaks": human["confirmed_breaks"],
            "duplicates": duplicates,
            "summary": {"total": len(internal), "matched": len(matches),
                        "pending_review": len(human["pending"]), "fuzzy_pairs": len(pairs),
                        "llm_suggestions": len(llm),
                        "by_method": dict(Counter(m["method"] for m in matches))}}
