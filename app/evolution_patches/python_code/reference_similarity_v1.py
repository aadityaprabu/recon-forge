"""Draft fuzzy reference scorer. Higher scores mean more similar references.

This score ranks candidates; it does not authorize a financial match.
"""
from difflib import SequenceMatcher
import re


def normalize(value: str) -> str:
    value = value.upper().strip()
    if value.startswith("P/"):
        value = value[2:]
    if value.endswith("-SETTLED"):
        value = value[:-8]
    value = re.sub(r"[^A-Z0-9]", "", value)
    return value[3:] if re.fullmatch(r"PAY\d+", value) else value


def reference_similarity(ledger_reference: str, settlement_reference: str) -> float:
    left, right = normalize(ledger_reference), normalize(settlement_reference)
    if not left or not right:
        return 0.0
    # Symmetric score avoids dependence on which source is the first argument.
    return min(SequenceMatcher(None, left, right, autojunk=False).ratio(),
               SequenceMatcher(None, right, left, autojunk=False).ratio())
