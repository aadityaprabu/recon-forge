"""Cascade priority, one-to-one safety, fuzzy evidence, and LLM/human boundaries."""
import asyncio
import json

from app.schemas import MatchingPolicy
from app.tools.analytics import detect_incidents
from app.tools.match_cascade import (match_by_fuzzy_score, match_by_human, match_by_id, match_by_llm,
                                     match_by_rule, run_cascade)

POLICY = MatchingPolicy()


def ledger(n, **overrides):
    return {"internal_record_id": f"INT-{n}", "merchant_id": "MRC_001", "customer_id": "CUST-1",
            "processor": "PROC_A", "channel": "card", "country": "US", "amount_cents": 10_000,
            "currency": "USD", "settlement_date": "2026-09-01", "reference": f"PAY-{100000 + n}", **overrides}


def settlement(n, **overrides):
    row = ledger(n, **overrides)
    row["processor_record_id"] = overrides.get("processor_record_id", f"SET-{n}")
    row["received_time"] = overrides.get("received_time", f"2026-09-01T09:00:{n % 60:02d}")
    del row["internal_record_id"]
    return row


def test_id_requires_exact_reference_and_fixed_checks():
    result = match_by_id([ledger(1), ledger(2)], [settlement(1), settlement(2, reference="pay-100002")], POLICY)
    assert [m["processor_record_id"] for m in result["matches"]] == ["SET-1"]
    assert [r["internal_record_id"] for r in result["unmatched"]] == ["INT-2"]


def test_rule_accepts_cleaned_reference():
    result = match_by_rule([ledger(2)], [settlement(2, reference="pay-100002")], POLICY)
    assert result["matches"][0]["method"] == "rule"


def test_fuzzy_pairs_and_measures_the_difference_without_matching():
    short_and_late = settlement(3, amount_cents=9_997, settlement_date="2026-09-02")
    other_customer = settlement(4, reference="PAY-100003", customer_id="CUST-2")
    result = match_by_fuzzy_score([ledger(3)], [short_and_late, other_customer], POLICY)
    assert "matches" not in result
    [pair] = result["pairs"]
    assert pair["processor_record_id"] == "SET-3"
    evidence = pair["evidence"]
    assert (evidence["amount_delta_cents"], evidence["date_delta_days"]) == (-3, 1)
    assert evidence["checks"]["amount_patch"] is False and evidence["checks"]["customer"] is True
    # A reference typo on top of other differences is too weak to pair.
    typo = settlement(3, reference="PAY-100030", amount_cents=9_997, settlement_date="2026-09-02")
    assert match_by_fuzzy_score([ledger(3)], [typo], POLICY)["pairs"] == []


def test_fuzzy_skips_high_value_large_gaps_and_close_runner_up():
    big = ledger(5, amount_cents=2_000_000)
    assert match_by_fuzzy_score([big], [settlement(5, amount_cents=2_000_000, reference="PAY-100050")],
                                POLICY)["pairs"] == []
    assert match_by_fuzzy_score([ledger(5)], [settlement(5, amount_cents=10_050)], POLICY)["pairs"] == []
    twins = [settlement(6, reference="PAY-100060"), settlement(7, reference="PAY-100060")]
    assert match_by_fuzzy_score([ledger(6)], twins, POLICY)["pairs"] == []


def test_llm_suggestion_must_name_a_supplied_candidate():
    async def invents(payload):
        return json.dumps({"internal_record_id": payload["ledger"]["internal_record_id"],
                           "processor_record_id": "SET-999", "confidence": 0.99, "reason": "made up"})

    async def picks(payload):
        return {"internal_record_id": payload["ledger"]["internal_record_id"],
                "processor_record_id": payload["candidates"][0]["processor_record_id"],
                "confidence": 0.9, "reason": "same customer and amount"}

    rows, pool = [ledger(8)], [settlement(8, reference="XYZ")]
    assert asyncio.run(match_by_llm(rows, pool, invents))["suggestions"] == []
    assert asyncio.run(match_by_llm(rows, pool, picks))["suggestions"][0]["processor_record_id"] == "SET-8"


def test_human_decisions_are_validated_and_one_to_one():
    rows, pool = [ledger(9), ledger(10), ledger(11)], [settlement(9)]
    result = match_by_human(rows, pool, [], {"INT-9": "SET-9", "INT-10": "SET-9", "INT-11": None})
    assert result["matches"] == []
    assert result["confirmed_breaks"] == ["INT-11"]
    assert {p["internal_record_id"] for p in result["pending"]} == {"INT-9", "INT-10"}


def test_cascade_keeps_fuzzy_pairs_open_and_human_can_accept_them():
    rows = [ledger(1), ledger(2), ledger(12)]
    pool = [settlement(1), settlement(2, reference="pay-100002"), settlement(12, amount_cents=9_997)]

    first = asyncio.run(run_cascade(rows, pool, POLICY))
    assert first["summary"]["by_method"] == {"id": 1, "rule": 1}
    [case] = first["cases"]
    assert case["break_type"] == "AMOUNT_MISMATCH" and case["fuzzy_pair"]["amount_delta_cents"] == -3
    assert first["pending_review"][0]["suggestion"]["method"] == "fuzzy"

    second = asyncio.run(run_cascade(rows, pool, POLICY, decisions={"INT-12": "SET-12"}))
    assert second["summary"]["by_method"] == {"id": 1, "rule": 1, "human": 1}
    assert second["cases"] == []
    used = [m["processor_record_id"] for m in second["matches"]]
    assert len(used) == len(set(used))


def test_llm_only_reviews_rows_fuzzy_could_not_pair():
    seen = []

    async def reviewer(payload):
        seen.append(payload["ledger"]["internal_record_id"])
        return {"internal_record_id": payload["ledger"]["internal_record_id"], "processor_record_id": None,
                "confidence": 0.9, "reason": "no plausible partner"}

    rows = [ledger(13), ledger(14)]
    pool = [settlement(13, amount_cents=9_997), settlement(14, reference="ZZZ", settlement_date="2026-09-05")]
    asyncio.run(run_cascade(rows, pool, POLICY, reviewer=reviewer))
    assert seen == ["INT-14"]


def test_fuzzy_pair_supplies_incident_evidence_the_matcher_could_not():
    # Each ledger row shares its reference with a second customer's settlement, so the
    # matcher sees two candidates and records AMBIGUOUS with no evidence. Fuzzy keeps
    # only the same-customer partner, which is 3 cents short.
    rows, pool = [], []
    for n in range(20, 32):
        rows.append(ledger(n, processor="PROC_C"))
        pool.append(settlement(n, processor="PROC_C", amount_cents=9_997))
        pool.append(settlement(n, processor="PROC_C", customer_id="CUST-9", processor_record_id=f"SET-X{n}"))
    result = asyncio.run(run_cascade(rows, pool, POLICY))
    assert all(c["evidence"]["source"] == "fuzzy" for c in result["cases"])
    [incident] = detect_incidents(result["cases"])
    assert (incident["processor"], incident["delta"], incident["count"]) == ("PROC_C", -3, 12)
    assert incident["evidence_sources"] == {"fuzzy": 12}
