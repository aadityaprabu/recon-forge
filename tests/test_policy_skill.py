import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.agents import create_agents
from app.evolution_patches.policies.policy_skill import ROOT, load_policy_skill


class PolicySkillTests(unittest.IsolatedAsyncioTestCase):
    async def test_evolution_receives_skill_and_analysis_receives_policy_rules(self):
        skill = load_policy_skill()
        with patch('app.agents.gemini_model', return_value='gemini-2.0-flash'):
            agents = create_agents('unused', policy_skill=skill)
        self.assertEqual(set(agents), {'diagnosis', 'analysis', 'evolution'})
        instruction, bypass = await agents['evolution'].canonical_instruction(None)
        analysis, analysis_bypass = await agents['analysis'].canonical_instruction(None)
        self.assertTrue(bypass)
        self.assertTrue(analysis_bypass)
        self.assertIn(skill['instructions'], instruction)
        self.assertIn('processor_overrides.{processor}.fees.fixed_fee_cents', instruction)
        self.assertIn('fixed_fee_cents', analysis)
        self.assertEqual(len(skill['sha256']), 64)

    def test_rule_bounds_cannot_override_runtime_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / 'SKILL.md').write_text((ROOT / 'SKILL.md').read_text())
            rules = json.loads((ROOT / 'rules.json').read_text())
            rules['parameters']['fixed_fee_cents']['maximum'] = 10000
            (target / 'rules.json').write_text(json.dumps(rules))
            with patch('app.evolution_patches.policies.policy_skill.ROOT', target):
                with self.assertRaisesRegex(ValueError, 'limits differ'):
                    load_policy_skill()

    def test_changed_skill_is_fingerprinted_for_reproducibility(self):
        original = load_policy_skill()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / 'SKILL.md').write_text(original['instructions'] + '\nAdditional explanation.\n')
            (target / 'rules.json').write_text(json.dumps(original['rules']))
            with patch('app.evolution_patches.policies.policy_skill.ROOT', target):
                self.assertNotEqual(original['sha256'], load_policy_skill()['sha256'])
