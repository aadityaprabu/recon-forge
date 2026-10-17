import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.demo.scale_dataset import generate_split
from app.demo.scenarios import advance, seed
from app.schemas import Policy, EvolutionResult, apply_patch
from scripts.verify_scale_demo import verify
from app.config import ROOT
from app.demo.generator import Dataset


class ScaleDatasetTests(unittest.IsolatedAsyncioTestCase):
    def test_ten_evidence_driven_single_field_changes_pass_fixed_guardrails(self):
        report = verify(Dataset(ROOT / "ReconForge_Scale5000_Dataset"))
        self.assertEqual(report["live_records"], 5000)
        self.assertEqual(report["validated_evolutions"], 10)
        self.assertEqual([s["accuracy_after"] for s in report["steps"]], list(range(25, 71, 5)))
        self.assertEqual([s["held_out_accuracy_after"] for s in report["steps"]], list(range(25, 71, 5)))
        self.assertEqual(len({s["field"].split('.')[-1] for s in report["steps"]}), 4)
        self.assertTrue(all(s["changed_fields"] == 1 and s["false_matches"] == 0 and
                            s["held_out_false_matches"] == 0 and s["accuracy_gain_pp"] == 5
                            for s in report["steps"]))

    def test_deterministic_pairs_and_no_label_leakage(self):
        first = generate_split("live")
        self.assertEqual(first, generate_split("live"))
        ledger, settlements, truth = first
        self.assertEqual(len(truth), 5000)
        self.assertEqual(len({r['internal_record_id'] for r in ledger}), 5000)
        self.assertEqual(len({r['processor_record_id'] for r in settlements}), 5000)
        self.assertEqual(sum(r["is_true_match"] == 0 for r in truth), 500)
        self.assertGreater(len({r["pattern"] for r in truth}), 10)
        self.assertTrue(all("label_group_id" not in row and "pattern" not in row
                            for row in ledger + settlements))
        self.assertFalse(set(r['internal_record_id'] for r in ledger) &
                         set(r['internal_record_id'] for r in generate_split('historical')[0]))

    async def test_stream_waits_for_completed_phase_not_just_a_candidate(self):
        db = SimpleNamespace(control=AsyncMock(), workflow_runs=AsyncMock())
        cursor = {"position": 500, "total": 5000, "phase_size": 500,
                  "pause_between_phases": True, "dataset_id": "scale5000-v1"}
        db.control.find_one.return_value = cursor
        db.control.find_one_and_update.return_value = cursor
        db.workflow_runs.find_one.return_value = None
        dataset = SimpleNamespace(business=Mock())
        result = await advance(db, dataset, 5000)
        self.assertEqual(result["position"], 500)
        self.assertEqual(result["status"], "WAITING_FOR_PHASE_APPROVAL")
        dataset.business.assert_not_called()
        self.assertEqual(db.workflow_runs.find_one.call_args.args[0]["status"], "COMPLETED")

    async def test_cannot_mix_datasets_in_existing_database(self):
        db = SimpleNamespace(control=AsyncMock())
        db.control.find_one.return_value = {"position": 1500, "total": 1500}
        dataset = Dataset(ROOT / "ReconForge_Scale5000_Dataset")
        with self.assertRaisesRegex(ValueError, "separate MONGODB_DB"):
            await seed(db, dataset)

    async def test_large_ingestion_request_cannot_skip_a_phase(self):
        db = AsyncMock()
        db.__getitem__.side_effect = lambda name: getattr(db, name)
        cursor = {"position": 490, "total": 5000, "phase_size": 500,
                  "pause_between_phases": True, "dataset_id": "scale5000-v1"}
        db.control.find_one.return_value = cursor
        db.control.find_one_and_update.return_value = cursor
        dataset = SimpleNamespace(business=Mock(return_value=(
            [{"internal_record_id": str(i)} for i in range(5000)],
            [{"processor_record_id": str(i)} for i in range(5000)])))
        result = await advance(db, dataset, 5000)
        self.assertEqual(result["position"], 500)
        self.assertEqual(db.internal_ledger.update_one.await_count, 10)
        self.assertEqual(db.processor_settlement.update_one.await_count, 10)

    def test_noop_patch_and_bundled_changes_rejected(self):
        proposal = EvolutionResult(parent_version="v1", candidate_patch={"processor": "PROC_A", "amount_tolerance_cents": 0},
                                   reason="test", expected_effect="test", risk="test")
        with self.assertRaisesRegex(ValueError, "no-op"):
            apply_patch(Policy(version="v1"), proposal, "v2")
        with self.assertRaises(ValueError):
            EvolutionResult(parent_version="v1", candidate_patch={"processor": "PROC_A", "amount_tolerance_cents": 1,
                            "settlement_window_days": 5}, reason="test", expected_effect="test", risk="test")
