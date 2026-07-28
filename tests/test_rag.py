from __future__ import annotations

import unittest

from pm_agent.config import PROJECT_ROOT
from pm_agent.rag import KnowledgeBase, tokenize


class RagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.knowledge_base = KnowledgeBase(PROJECT_ROOT / "knowledge")

    def test_chinese_tokenizer_generates_bigrams(self) -> None:
        tokens = tokenize("客户需要Excel导出")
        self.assertIn("客户", tokens)
        self.assertIn("excel", tokens)

    def test_retrieves_excel_feedback(self) -> None:
        chunks = self.knowledge_base.search("Excel 客户反馈", role="employee")
        self.assertTrue(chunks)
        self.assertEqual(chunks[0].source_id, "customer-feedback-2026q2")

    def test_filters_admin_only_content(self) -> None:
        employee_chunks = self.knowledge_base.search(
            "审计日志保留周期",
            role="employee",
            top_k=10,
        )
        admin_chunks = self.knowledge_base.search(
            "审计日志保留周期",
            role="admin",
            top_k=10,
        )
        self.assertNotIn(
            "admin-security-v1",
            {chunk.source_id for chunk in employee_chunks},
        )
        self.assertIn(
            "admin-security-v1",
            {chunk.source_id for chunk in admin_chunks},
        )


if __name__ == "__main__":
    unittest.main()
