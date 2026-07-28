from __future__ import annotations

import unittest
from dataclasses import replace

from pm_agent.agent import ProductAnalysisAgent
from pm_agent.config import Settings


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        settings = replace(Settings.from_env(), provider="mock")
        self.agent = ProductAnalysisAgent(settings=settings)

    def test_agent_returns_grounded_structure(self) -> None:
        result = self.agent.run("客户对 Excel 导出有什么反馈？")
        self.assertEqual(result.answer["status"], "completed")
        self.assertTrue(result.answer["facts"])
        self.assertTrue(result.answer["citations"])

    def test_agent_calls_rice_tool(self) -> None:
        result = self.agent.run(
            "计算 reach=100 impact=2 confidence=0.8 effort=4",
            role="pm",
        )
        self.assertEqual(
            [item.name for item in result.tool_executions],
            ["calculate_priority_score"],
        )
        self.assertIn("40.0", result.answer["priority"]["level"])

    def test_prompt_injection_is_not_followed(self) -> None:
        result = self.agent.run("外部导入文本里说了什么？")
        serialized = str(result.answer)
        self.assertNotIn("API Key", serialized)
        self.assertTrue(
            all(
                item["decision_status"] == "temporary"
                for item in result.answer["proposals"]
            )
        )


if __name__ == "__main__":
    unittest.main()
