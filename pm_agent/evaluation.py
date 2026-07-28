from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent import ProductAnalysisAgent


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    checks: dict[str, bool]
    details: dict[str, Any]


def load_golden(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def evaluate_case(
    agent: ProductAnalysisAgent,
    case: dict[str, Any],
) -> CaseResult:
    result = agent.run(
        query=case["query"],
        role=case.get("role", "employee"),
        approval_callback=lambda _name, _arguments: case.get(
            "approve_writes",
            False,
        ),
    )
    serialized_answer = json.dumps(result.answer, ensure_ascii=False)
    retrieved_sources = {chunk.source_id for chunk in result.retrieved}
    called_tools = {item.name for item in result.tool_executions}

    expected_sources = set(case.get("expected_source_ids", []))
    expected_tools = set(case.get("expected_tools", []))
    forbidden_claims = case.get("forbidden_claims", [])
    checks = {
        "status": result.answer["status"] == case["expected_status"],
        "retrieval": expected_sources.issubset(retrieved_sources),
        "tools": expected_tools.issubset(called_tools),
        "forbidden_claims": not any(
            claim in serialized_answer for claim in forbidden_claims
        ),
        "citations_resolve": all(
            any(
                citation["source_id"] == chunk.chunk_id
                for chunk in result.retrieved
            )
            for citation in result.answer["citations"]
        ),
    }
    return CaseResult(
        case_id=case["id"],
        passed=all(checks.values()),
        checks=checks,
        details={
            "status": result.answer["status"],
            "retrieved_sources": sorted(retrieved_sources),
            "called_tools": sorted(called_tools),
            "run_id": result.run_id,
        },
    )


def run_evaluation(
    agent: ProductAnalysisAgent,
    golden_path: Path,
) -> dict[str, Any]:
    results = [
        evaluate_case(agent, case)
        for case in load_golden(golden_path)
    ]
    passed = sum(result.passed for result in results)
    total = len(results)
    return {
        "summary": {
            "passed": passed,
            "total": total,
            "pass_rate": round(passed / max(total, 1), 4),
        },
        "cases": [
            {
                "case_id": result.case_id,
                "passed": result.passed,
                "checks": result.checks,
                "details": result.details,
            }
            for result in results
        ],
    }
