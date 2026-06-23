import os
import unittest

from zzcode.agent.context_budget import (
    ContextBudgetConfig,
    calculate_context_budget_state,
    check_context_budget,
    max_turns_from_env,
    rough_token_count,
)


class ContextBudgetTest(unittest.TestCase):
    def test_rough_token_count_uses_character_estimate(self) -> None:
        self.assertEqual(rough_token_count("abcd" * 10), 10)
        self.assertEqual(rough_token_count(""), 0)

    def test_budget_state_marks_auto_compact_and_blocking(self) -> None:
        config = ContextBudgetConfig(
            context_window_tokens=100,
            reserved_output_tokens=10,
            auto_compact_buffer_tokens=20,
            blocking_buffer_tokens=5,
        )

        compact_state = calculate_context_budget_state(70, config=config)
        blocking_state = calculate_context_budget_state(85, config=config)

        self.assertTrue(compact_state.is_above_auto_compact_threshold)
        self.assertFalse(compact_state.is_at_blocking_limit)
        self.assertTrue(blocking_state.is_at_blocking_limit)

    def test_check_context_budget_includes_tools_schema(self) -> None:
        config = ContextBudgetConfig(
            context_window_tokens=100,
            reserved_output_tokens=10,
            auto_compact_buffer_tokens=20,
            blocking_buffer_tokens=5,
        )
        state = check_context_budget(
            [{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "read_file", "description": "x" * 200}}],
            config=config,
        )

        self.assertGreater(state.estimated_tokens, rough_token_count("hello"))

    def test_max_turns_from_env_uses_positive_integer(self) -> None:
        old_value = os.environ.get("ZZCODE_MAX_TURNS")
        try:
            os.environ["ZZCODE_MAX_TURNS"] = "13"
            self.assertEqual(max_turns_from_env(), 13)
            os.environ["ZZCODE_MAX_TURNS"] = "bad"
            self.assertEqual(max_turns_from_env(default=9), 9)
        finally:
            if old_value is None:
                os.environ.pop("ZZCODE_MAX_TURNS", None)
            else:
                os.environ["ZZCODE_MAX_TURNS"] = old_value


if __name__ == "__main__":
    unittest.main()
