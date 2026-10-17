"""Reproducible 5,000-record stream with ten sequential single-leaf patches."""
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import random

SEED = 5000
PROCESSORS = ("PROC_A", "PROC_B", "PROC_C", "PROC_D")
PHASES = [
    ("PROC_A", "amount_tolerance_cents", 1),
    ("PROC_B", "amount_tolerance_cents", 2),
    ("PROC_C", "amount_tolerance_cents", 3),
    ("PROC_D", "settlement_window_days", 3),
    ("PROC_A", "settlement_window_days", 4),
    ("PROC_B", "settlement_window_days", 5),
    ("PROC_C", "fixed_fee_cents", 31),
    ("PROC_D", "fixed_fee_cents", 43),
    ("PROC_A", "fixed_fee_cents", 59),
    ("PROC_B", "fee_bps", 125),
]


def add_business_days(moment, days):
    while days:
        moment += timedelta(days=1)
        if moment.weekday() < 5:
            days -= 1
    return moment


def generate_split(split):
    rng = random.Random(SEED + (split == "live"))
    ledger, settlements, truth = [], [], []
    total = 5000 if split == "live" else 8000
    for i in range(total):
        if split == "live":
            phase, offset = divmod(i, 500)
            kind = "drift" if offset % 10 < 5 else "exact" if offset % 10 < 6 else "hard" if offset % 10 < 9 else "negative"
        else:
            phase, offset = divmod(i, 400)
            kind = "drift" if i < 4000 else "exact" if i < 4600 else "hard" if i < 7000 else "negative"
            phase = min(phase, 9)
        processor, patch_field, value = PHASES[phase]
        if kind != "drift":
            processor = rng.choice(PROCESSORS)
        moment = datetime(2026, 10, 1) + timedelta(minutes=i)
        ref = str((700000 if split == "live" else 100000) + i)
        row = {"internal_record_id": f"INT-SCALE-{split}-{i:05d}",
               "event_time": moment.isoformat(), "merchant_id": f"MRC_{rng.randrange(1, 20):03d}",
               "customer_id": f"CUST-{rng.randrange(1, 800):04d}", "processor": processor,
               "channel": rng.choice(["card", "wallet", "ach"]),
               "country": rng.choice(["US", "GB", "DE", "CA"]),
               "currency": rng.choice(["USD", "EUR", "GBP", "CAD"]),
               "amount_cents": rng.randrange(1_000_000, 2_000_000) if i % 37 == 0 else rng.randrange(100, 100000),
               "settlement_date": moment.date().isoformat(), "reference": f"PAY-{ref}", "status": "posted"}
        settlement = {k: v for k, v in row.items() if k not in ("internal_record_id", "event_time")}
        settlement.update(processor_record_id=f"SET-SCALE-{split}-{i:05d}",
                          received_time=(moment + timedelta(minutes=rng.randrange(1, 120))).isoformat(), status="settled")
        settlement["reference"] = rng.choice([f"P/{ref}", f"{ref}-SETTLED", f" pay-{ref} ", ref])
        settlement["settlement_date"] = (moment + timedelta(days=rng.choice([-2, -1, 0, 1, 2]))).date().isoformat()
        pattern = "exact_match"
        if kind == "drift":
            if patch_field == "settlement_window_days":
                settlement["settlement_date"] = add_business_days(moment, value).date().isoformat()
            elif patch_field == "fee_bps":
                # Exact monetary arithmetic and a range of gross amounts make
                # the proportional fee identifiable from evidence, not labels.
                row["amount_cents"] = rng.randrange(1, 151) * 10000
                settlement["amount_cents"] = row["amount_cents"] - (row["amount_cents"] * value + 5000) // 10000
            else:
                settlement["amount_cents"] -= value
            pattern = f"{patch_field}_{phase + 1:02d}"
        elif kind == "hard":
            # Real matches requiring future reference-recovery capabilities.
            # Policy amounts/dates/fees cannot repair these strings.
            if i % 2:
                settlement["reference"] = f"BANK-REF-{ref[:2]}X{ref[3:]}"
                pattern = "reference_typo_requires_fuzzy"
            else:
                settlement["reference"] = f"REF-{ref[-4:]}"
                pattern = "truncated_reference_requires_recovery"
        elif kind == "negative":
            # Negative controls cover independent fixed checks and amounts above
            # the maximum allowed tolerance. None should become a match.
            control = (i // (10 if split == "live" else 1)) % 7
            pattern = ["true_amount_mismatch", "currency_mismatch", "customer_mismatch",
                       "merchant_mismatch", "date_outlier", "reference_mismatch", "processor_mismatch"][control]
            if control == 0:
                settlement["amount_cents"] += rng.randrange(26, 500)
            elif control == 1:
                settlement["currency"] = "JPY"
            elif control == 2:
                settlement["customer_id"] = "OTHER-CUSTOMER"
            elif control == 3:
                settlement["merchant_id"] = "OTHER-MERCHANT"
            elif control == 4:
                settlement["settlement_date"] = add_business_days(moment, 7).date().isoformat()
            elif control == 5:
                settlement["reference"] = f"UNRELATED-{ref}"
            else:
                settlement["processor"] = PROCESSORS[(PROCESSORS.index(processor) + 1) % len(PROCESSORS)]
        ledger.append(row)
        settlements.append(settlement)
        truth.append({"label_group_id": f"LBL-SCALE-{split}-{i:05d}", "dataset_split": split,
                      "live_phase": f"phase_{phase + 1:02d}", "pattern": pattern,
                      "is_true_match": int(kind != "negative"),
                      "expected_internal_record_id": row["internal_record_id"],
                      "expected_processor_record_id": settlement["processor_record_id"]})
    # Paired duplicate ledgers and settlements must stay unresolved: a single
    # canonical settlement cannot be allocated to two internal transactions.
    negatives = [i for i, label in enumerate(truth) if not label["is_true_match"]]
    for offset in range(0, len(negatives) - 1, 50):
        left, right = negatives[offset:offset + 2]
        identity = {k: v for k, v in ledger[left].items()
                    if k not in ("internal_record_id", "event_time", "status")}
        ledger[right].update(identity)
        for index in (left, right):
            settlements[index].update(identity)
            truth[index]["pattern"] = "duplicate_allocation_ambiguity"
    return ledger, settlements, truth


def write_dataset(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for split in ("historical", "live"):
        for suffix, records in zip(("internal_ledger", "processor_settlement", "ground_truth"), generate_split(split)):
            (directory / f"{split}_{suffix}.json").write_text(json.dumps(records, indent=2) + "\n")
            with (directory / f"{split}_{suffix}.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(records[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows(records)
    manifest = {"project": "ReconForge", "dataset_id": "scale5000-four-processors-v6", "seed": SEED,
                "historical_base_pairs": 8000, "live_base_pairs": 5000,
                "baseline_policy_file": "policies/policy.json",
                "preserve_live_order": True, "phase_size": 500, "phase_count": 10,
                "pause_between_phases": True, "stream_batch_size": 25,
                "description": "Ten 500-pair phases: 250 policy drift, 50 exact, 150 hard reference matches, 50 invalid per phase. "
                               "Ten single-field policy changes across amounts, settlement windows, fixed fees and percentage fees. "
                               "Fixed benchmark accuracy: 20%, 25%, ..., 70%; 30% reference-recovery cases remain unresolved. "
                               "Includes duplicate-allocation ambiguity controls. "
                               "Requires human approval for each promoted version."}
    (directory / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with (directory / "incident_memories.csv").open("w", newline="") as handle:
        handle.write("memory_id,pattern_summary,successful_action,tags\n")
    return manifest
