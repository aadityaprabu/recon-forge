import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.policies import load_baseline, seed_policy
from app.schemas import Policy


class PolicyFileTests(unittest.IsolatedAsyncioTestCase):
    def test_baseline_is_the_latest_four_processor_policy(self):
        baseline = load_baseline()
        self.assertEqual(baseline.version, "v4.1-four-processor-baseline")
        self.assertEqual(len(baseline.processor_names), 4)
        self.assertEqual(baseline.settlement.day_basis, "business")

    async def test_seed_preserves_existing_active_policy(self):
        db = SimpleNamespace(harness_policies=AsyncMock(), control=AsyncMock())
        baseline = load_baseline()
        db.harness_policies.find_one.return_value = {"policy": baseline.model_dump()}
        await seed_policy(db, baseline)
        update = db.control.update_one.call_args.args[1]
        self.assertEqual(set(update), {"$setOnInsert"})
        self.assertEqual(update["$setOnInsert"]["policy"], baseline.model_dump())

    async def test_reusing_version_with_changed_content_is_rejected(self):
        db = SimpleNamespace(harness_policies=AsyncMock(), control=AsyncMock())
        existing = load_baseline().model_dump()
        existing["processor_overrides"]["PROC_A"] = {"amount_matching": {"absolute_tolerance_cents": 5}}
        db.harness_policies.find_one.return_value = {"policy": existing}
        with self.assertRaises(ValueError):
            await seed_policy(db, load_baseline())
        db.harness_policies.update_one.assert_not_awaited()
        db.control.update_one.assert_not_awaited()
