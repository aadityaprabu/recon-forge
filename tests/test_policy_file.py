import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.policies import load_baseline, seed_policy
from app.schemas import Policy


class PolicyFileTests(unittest.IsolatedAsyncioTestCase):
    def test_baseline_preserves_runtime_defaults(self):
        self.assertEqual(load_baseline(), Policy(version="v1"))

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
        existing["matching"]["processor_amount_tolerance_cents"]["PROC_A"] = 5
        db.harness_policies.find_one.return_value = {"policy": existing}
        with self.assertRaises(ValueError):
            await seed_policy(db, load_baseline())
        db.harness_policies.update_one.assert_not_awaited()
        db.control.update_one.assert_not_awaited()
