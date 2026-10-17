"""Fixed identity/allocation contracts and bounded, declarative financial rules."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import re


def normalize_reference(value):
    value = value.upper().strip()
    if value.startswith("P/"):
        value = value[2:]
    if value.endswith("-SETTLED"):
        value = value[:-8]
    value = re.sub(r"[^A-Z0-9]", "", value)
    return value[3:] if re.fullmatch(r"PAY\d+", value) else value


def check_customer(ledger, settlement):
    return ledger["customer_id"] == settlement["customer_id"]


def check_currency(ledger, settlement):
    return ledger["currency"] == settlement["currency"]


def check_merchant(ledger, settlement):
    return ledger["merchant_id"] == settlement["merchant_id"]


def check_processor(ledger, settlement):
    return ledger["processor"] == settlement["processor"]


def check_reference(ledger, settlement):
    return normalize_reference(ledger["reference"]) == normalize_reference(settlement["reference"])


def local_settlement_date(value, timezone="America/New_York"):
    if "T" not in value and " " not in value:
        return date.fromisoformat(value)
    timestamp = datetime.fromisoformat(value)
    zone = ZoneInfo(timezone)
    return timestamp.replace(tzinfo=zone).date() if timestamp.tzinfo is None else timestamp.astimezone(zone).date()


def business_day_distance(left, right):
    start, end = sorted((left, right))
    count = 0
    while start < end:
        start += timedelta(days=1)
        count += start.weekday() < 5
    return count


def check_date_boundary(ledger, settlement, window_days=2, policy=None):
    zone = policy.timezone if policy else "America/New_York"
    left = local_settlement_date(ledger["settlement_date"], zone)
    right = local_settlement_date(settlement["settlement_date"], zone)
    distance = business_day_distance(left, right) if policy and policy.day_basis == "business" else abs((right - left).days)
    grace = policy.processor_weekend_grace_days[ledger["processor"]] if policy and (left.weekday() >= 5 or right.weekday() >= 5) else 0
    return distance <= window_days + grace


def expected_settlement_amounts(ledger, patch):
    processor = ledger["processor"]
    gross = ledger["amount_cents"]
    fixed = patch.processor_fixed_fee_cents[processor]
    quotient, remainder = divmod(gross * patch.processor_fee_bps[processor], 10000)
    percentage = quotient + int(remainder > 5000 or (remainder == 5000 and (patch.fee_rounding == "half_up" or quotient % 2 == 1)))
    # Explicit supported settlement forms: gross, fixed-fee net, percentage-fee
    # net. No automatic stacking of fees or agent-generated executable code.
    return (gross,) if patch.fee_treatment == "gross_only" else (gross, gross - fixed, gross - percentage)


def check_amount_patch(ledger, settlement, patch):
    tolerance = patch.processor_amount_tolerance_cents.get(ledger["processor"], 0)
    gross = ledger["amount_cents"]
    tolerance = min(patch.maximum_tolerance_cents, max(tolerance, (abs(gross) * patch.relative_tolerance_bps + 9999) // 10000))
    return any(abs(expected - settlement["amount_cents"]) <= tolerance
               for expected in expected_settlement_amounts(ledger, patch))


CHECKS = {"customer": check_customer, "currency": check_currency, "merchant": check_merchant,
          "processor": check_processor, "reference": check_reference, "date": check_date_boundary}


def make_match_decision(ledger, settlement, active_patch):
    checks = {name: function(ledger, settlement) for name, function in CHECKS.items()}
    checks["date"] = check_date_boundary(ledger, settlement, active_patch.processor_settlement_window_days[ledger["processor"]], active_patch)
    checks["amount_patch"] = check_amount_patch(ledger, settlement, active_patch)
    return {"decision": "MATCH" if all(checks.values()) else "BREAK", "checks": checks}
