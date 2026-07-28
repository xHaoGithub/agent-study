from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from typing import Any

from .agent import ProductAnalysisAgent
from .config import Settings
from .evaluation import run_evaluation
from .rag import KnowledgeBase


def _approval_callback(always_approve: bool):
    def approve(name: str, arguments: dict[str, Any]) -> bool:
        if always_approve:
            return True
        if not sys.stdin.isatty():
            return False
        print(f"\nAgent 请求执行写工具：{name}")
        print(json.dumps(arguments, ensure_ascii=False, indent=2))
        reply = input("允许执行吗？输入 yes 批准：").strip().lower()
        return reply in {"yes", "y"}

    return approve


def _print_human_result(payload: dict[str, Any]) -> None:
    answer = payload["answer"]
    print(f"\n状态：{answer['status']}")
    print(f"结论：{answer['summary']}")
    print(f"置信度：{answer['confidence']:.0%}")
    print("\n事实：")
    for item in answer["facts"]:
        print(f"- {item['statement']}  [{', '.join(item['source_ids'])}]")
    print("\n推断：")
    for item in answer["inferences"]:
        print(
            f"- {item['statement']}（{item['validation_status']}；{item['basis']}）"
        )
    print("\n暂定方案：")
    for item in answer["proposals"]:
        print(f"- {item['proposal']}；风险：{item['risk']}")
    priority = answer["priority"]
    print(f"\n优先级：{priority['level']}")
    print(f"依据：{priority['basis']}")
    if priority["missing_data"]:
        print(f"缺失数据：{', '.join(priority['missing_data'])}")
    if answer["questions"]:
        print("\n待确认：")
        for question in answer["questions"]:
            print(f"- {question}")
    if payload["tool_executions"]:
        print("\n工具执行：")
        for execution in payload["tool_executions"]:
            print(
                f"- {execution['name']} | 风险={execution['risk']} | "
                f"approved={execution['approved']} | result={execution['result']}"
            )
    print(f"\nTrace ID：{payload['run_id']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="产品需求分析 Agent 教学项目",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="运行一次 Agent 分析")
    analyze.add_argument("query", help="要分析的产品问题")
    analyze.add_argument("--role", default="employee", help="知识权限角色")
    analyze.add_argument(
        "--provider",
        choices=["mock", "openai"],
        help="临时覆盖 MODEL_PROVIDER",
    )
    analyze.add_argument(
        "--approve-writes",
        action="store_true",
        help="自动批准写工具，仅建议在本地教学时使用",
    )
    analyze.add_argument("--json", action="store_true", help="输出完整 JSON")

    retrieve = subparsers.add_parser("retrieve", help="只观察 RAG 检索结果")
    retrieve.add_argument("query")
    retrieve.add_argument("--role", default="employee")
    retrieve.add_argument("--top-k", type=int, default=4)

    evaluate = subparsers.add_parser("eval", help="运行 Golden Dataset 评测")
    evaluate.add_argument(
        "--provider",
        choices=["mock", "openai"],
        default="mock",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = Settings.from_env()

    if args.command == "retrieve":
        knowledge_base = KnowledgeBase(settings.knowledge_dir)
        chunks = knowledge_base.search(args.query, args.role, args.top_k)
        print(
            json.dumps(
                [chunk.to_dict() for chunk in chunks],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    provider = getattr(args, "provider", None)
    if provider:
        settings = replace(settings, provider=provider)
    agent = ProductAnalysisAgent(settings=settings)

    if args.command == "eval":
        report = run_evaluation(
            agent,
            settings.project_root / "evals" / "golden.jsonl",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["summary"]["passed"] == report["summary"]["total"] else 1

    result = agent.run(
        query=args.query,
        role=args.role,
        approval_callback=_approval_callback(args.approve_writes),
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human_result(payload)
    return 0
