import unittest

from hll.domain import ActionKind
from hll.executor import HLL_OBSERVATION_ACTIONS, HLL_TOOL_ACTIONS
from hll.tools import build_default_registry, build_observation_registry


class ToolRegistryTests(unittest.TestCase):
    def test_tool_spec_exposes_mcp_style_schema(self):
        registry = build_default_registry()
        spec = registry.spec_for_action(ActionKind.TAP_GRID_CELL)

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.name, "TapGridCell")
        self.assertEqual(spec.input_schema["required"], ["index"])
        self.assertIn("index", spec.input_schema["properties"])

    def test_prompt_block_is_generated_from_tool_specs(self):
        prompt = build_default_registry().prompt_block()

        self.assertIn("tap_grid_cell args_schema=", prompt)
        self.assertIn("tool=TapGridCell", prompt)
        self.assertIn("estimate_drag_offset args_schema=", prompt)
        self.assertIn("read_only=True", prompt)
        self.assertIn("move_grid_piece args_schema=", prompt)
        self.assertIn("affordances=continuous_slider", prompt)
        self.assertIn("preconditions=visible_handle,visible_track", prompt)

    def test_executor_actions_have_registered_tool_specs(self):
        default_registry = build_default_registry()
        observation_registry = build_observation_registry()

        missing_default_specs = [
            kind.value
            for kind in HLL_TOOL_ACTIONS - HLL_OBSERVATION_ACTIONS
            if default_registry.spec_for_action(kind) is None
        ]
        missing_observation_specs = [
            kind.value
            for kind in HLL_OBSERVATION_ACTIONS
            if observation_registry.spec_for_action(kind) is None
        ]

        self.assertEqual(missing_default_specs, [])
        self.assertEqual(missing_observation_specs, [])


if __name__ == "__main__":
    unittest.main()
