from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pm_agent.tools import ToolRegistry, calculate_priority_score


class ToolTests(unittest.TestCase):
    def test_rice_formula(self) -> None:
        result = calculate_priority_score(
            {
                "reach": 100,
                "impact": 2,
                "confidence": 0.8,
                "effort": 4,
            }
        )
        self.assertEqual(result["rice_score"], 40.0)

    def test_write_tool_is_denied_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = ToolRegistry(Path(directory))
            result, approved, risk = registry.execute(
                "save_analysis_draft",
                {
                    "title": "测试",
                    "summary": "内容",
                    "priority": "暂定",
                },
                approval_callback=lambda _name, _arguments: False,
            )
            self.assertFalse(approved)
            self.assertEqual(risk, "write")
            self.assertEqual(result["status"], "denied")
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
