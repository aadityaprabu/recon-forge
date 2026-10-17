import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.evolution_patches import local_versions, seed_patch_versions
from app.evolution_patches.python_code.reference_similarity_v1 import reference_similarity


class PatchVersionTests(unittest.IsolatedAsyncioTestCase):
    async def test_versions_preserve_existing_records(self):
        collection = AsyncMock()
        collection.find_one.return_value = None
        count = await seed_patch_versions(SimpleNamespace(evolution_patch_versions=collection))
        self.assertEqual(count, len(list(local_versions())))
        for call in collection.update_one.call_args_list:
            self.assertEqual(set(call.args[1]), {"$setOnInsert"})

    async def test_rewriting_version_is_rejected(self):
        collection = AsyncMock()
        first = next(local_versions())
        collection.find_one.return_value = {**first, "sha256": "changed"}
        with self.assertRaisesRegex(ValueError, "Immutable patch"):
            await seed_patch_versions(SimpleNamespace(evolution_patch_versions=collection))
        collection.update_one.assert_not_awaited()

    async def test_identical_content_can_move_to_policy_json(self):
        artifacts = list(local_versions())
        collection = AsyncMock()
        collection.find_one.side_effect = [{**artifacts[0], "file": "policies/previous_name.json"}] + [None] * (len(artifacts) - 1)
        count = await seed_patch_versions(SimpleNamespace(evolution_patch_versions=collection))
        self.assertEqual(count, len(artifacts))

    def test_reference_score_handles_formatting_and_empty_values(self):
        self.assertEqual(reference_similarity("PAY12345", "P/12345-SETTLED"), 1)
        self.assertEqual(reference_similarity("", ""), 0)
        self.assertLess(reference_similarity("12345", "67890"), 0.5)
        self.assertEqual(reference_similarity("tide", "diet"), reference_similarity("diet", "tide"))
