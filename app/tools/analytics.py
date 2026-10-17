"""Detect bounded policy incidents from business evidence, never evaluator labels."""
from collections import Counter, defaultdict

INCIDENT_MIN_CLUSTER_CASES = 10
INCIDENT_MIN_SIGNED_DELTA_CONCENTRATION = 0.70


def detect_incidents(cases: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for case in cases:
        if case['break_type'] in {'AMOUNT_MISMATCH', 'DATE_BOUNDARY'} and case['evidence']:
            groups[(case['processor'], case['break_type'])].append(case)
    incidents = []
    for (processor, kind), rows in groups.items():
        field = 'date_delta_days' if kind == 'DATE_BOUNDARY' else 'amount_delta_cents'
        delta, count = Counter(r['evidence'][field] for r in rows).most_common(1)[0]
        concentration = count / len(rows)
        patch_field = None
        value = abs(delta)
        if count >= INCIDENT_MIN_CLUSTER_CASES and concentration >= INCIDENT_MIN_SIGNED_DELTA_CONCENTRATION:
            if kind == 'DATE_BOUNDARY' and value <= 5:
                patch_field = 'settlement_window_days'
            elif kind == 'AMOUNT_MISMATCH' and value <= 25:
                patch_field = 'amount_tolerance_cents'
            elif kind == 'AMOUNT_MISMATCH' and delta < 0 and value <= 100:
                patch_field = 'fixed_fee_cents'
        if patch_field is None and kind == 'AMOUNT_MISMATCH':
            rates = []
            for row in rows:
                evidence = row['evidence']
                gross = evidence.get('ledger_amount_cents', 0)
                amount_delta = evidence['amount_delta_cents']
                if gross > 0 and amount_delta < 0:
                    bps = round(-amount_delta * 10000 / gross)
                    if 0 < bps <= 300 and (gross * bps + 5000) // 10000 == -amount_delta:
                        rates.append(bps)
            if rates:
                value, count = Counter(rates).most_common(1)[0]
                concentration = count / len(rows)
                if count >= INCIDENT_MIN_CLUSTER_CASES and concentration >= INCIDENT_MIN_SIGNED_DELTA_CONCENTRATION:
                    patch_field, field, delta = 'fee_bps', 'inferred_fee_bps', value
        if patch_field:
            incidents.append({'processor': processor, 'break_type': kind, 'delta_field': field,
                              'delta': delta, 'patch_field': patch_field, 'suggested_value': value,
                              'count': count, 'cluster_size': len(rows), 'concentration': concentration,
                              'constant_checks_passed': {name: sum(r['evidence']['checks'][name] for r in rows)
                                  for name in ('customer', 'currency', 'merchant', 'processor', 'reference', 'date')}})
    return sorted(incidents, key=lambda i: (-i['count'], i['processor']))
