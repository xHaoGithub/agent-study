from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .config import Settings
from .model import ResponsesClient, build_client, extract_output_text
from .prompts import (
    ANSWER_SCHEMA,
    DEVELOPER_INSTRUCTIONS,
    PROMPT_VERSION,
    build_user_input,
)
from .rag import KnowledgeBase
from .tools import ApprovalCallback, ToolRegistry
from .trace import TraceLogger
from .types import RunResult, ToolExecution


REQUIRED_ANSWER_KEYS = set(ANSWER_SCHEMA["required"])


def validate_answer(answer: dict[str, Any]) -> None:
    missing = REQUIRED_ANSWER_KEYS - set(answer)
    extra = set(answer) - set(ANSWER_SCHEMA["properties"])
    if missing:
        raise ValueError(f"模型结构化输出缺少字段：{sorted(missing)}")
    if extra:
        raise ValueError(f"模型结构化输出包含未知字段：{sorted(extra)}")
    if answer["status"] not in {"completed", "needs_clarification", "refused"}:
        raise ValueError("模型输出了不支持的 status")
    confidence = answer["confidence"]
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("confidence 必须是 0 到 1 的数字")


class ProductAnalysisAgent:
    def __init__(
        self,
        settings: Settings | None = None,
        client: ResponsesClient | None = None,
    ):
        self.settings = settings or Settings.from_env()
        if (
            self.settings.temperature is not None
            and self.settings.top_p is not None
        ):
            raise ValueError("temperature 与 top_p 建议只调整一个，本项目不允许同时设置。")
        self.client = client or build_client(self.settings)
        self.knowledge_base = KnowledgeBase(self.settings.knowledge_dir)
        self.tools = ToolRegistry(self.settings.draft_dir)
        self.trace = TraceLogger(self.settings.trace_path)

    def run(
        self,
        query: str,
        role: str = "employee",
        approval_callback: ApprovalCallback | None = None,
    ) -> RunResult:
        run_id = str(uuid.uuid4())
        started = time.perf_counter()
        self.trace.emit(
            run_id,
            "run_started",
            {
                "query": query,
                "role": role,
                "provider": self.settings.provider,
                "model": self.settings.model,
                "prompt_version": PROMPT_VERSION,
            },
        )

        chunks = self.knowledge_base.search(
            query=query,
            role=role,
            top_k=self.settings.top_k,
        )
        self.trace.emit(
            run_id,
            "retrieval_completed",
            {
                "count": len(chunks),
                "chunks": [
                    {
                        "chunk_id": chunk.chunk_id,
                        "score": chunk.score,
                        "version": chunk.version,
                    }
                    for chunk in chunks
                ],
            },
        )

        input_items: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": build_user_input(query, role, chunks),
            }
        ]
        executions: list[ToolExecution] = []

        for step in range(1, self.settings.max_agent_steps + 1):
            payload = self._build_payload(input_items)
            model_started = time.perf_counter()
            response = self.client.create(payload)
            model_latency_ms = round(
                (time.perf_counter() - model_started) * 1000,
                2,
            )
            output_items = list(response.get("output", []))
            self.trace.emit(
                run_id,
                "model_turn_completed",
                {
                    "step": step,
                    "response_id": response.get("id", ""),
                    "status": response.get("status", ""),
                    "latency_ms": model_latency_ms,
                    "output_types": [item.get("type") for item in output_items],
                    "usage": response.get("usage", {}),
                },
            )

            input_items.extend(output_items)
            function_calls = [
                item for item in output_items if item.get("type") == "function_call"
            ]
            if not function_calls:
                text = extract_output_text(response)
                if not text:
                    raise RuntimeError("模型既没有返回文本，也没有发起工具调用。")
                try:
                    answer = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"模型没有返回合法 JSON：{text[:300]}") from exc
                validate_answer(answer)
                self.trace.emit(
                    run_id,
                    "run_completed",
                    {
                        "status": answer["status"],
                        "total_latency_ms": round(
                            (time.perf_counter() - started) * 1000,
                            2,
                        ),
                        "tool_count": len(executions),
                        "citation_count": len(answer["citations"]),
                    },
                )
                return RunResult(
                    run_id=run_id,
                    answer=answer,
                    retrieved=chunks,
                    tool_executions=executions,
                    model=self.settings.model,
                    provider=self.settings.provider,
                    prompt_version=PROMPT_VERSION,
                )

            for call in function_calls:
                name = str(call.get("name", ""))
                try:
                    arguments = json.loads(str(call.get("arguments", "{}")))
                except json.JSONDecodeError:
                    arguments = {}
                    result = {
                        "tool": name,
                        "status": "error",
                        "error": "工具参数不是合法 JSON",
                    }
                    approved = False
                    risk = "unknown"
                else:
                    self.trace.emit(
                        run_id,
                        "tool_requested",
                        {"step": step, "name": name, "arguments": arguments},
                    )
                    try:
                        result, approved, risk = self.tools.execute(
                            name,
                            arguments,
                            approval_callback,
                        )
                    except ValueError as exc:
                        result = {
                            "tool": name,
                            "status": "error",
                            "error": str(exc),
                        }
                        approved = False
                        risk = "unknown"
                execution = ToolExecution(
                    name=name,
                    arguments=arguments,
                    result=result,
                    approved=approved,
                    risk=risk,
                )
                executions.append(execution)
                self.trace.emit(
                    run_id,
                    "tool_completed",
                    execution.to_dict(),
                )
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.get("call_id", ""),
                        "output": json.dumps(result, ensure_ascii=False),
                    }
                )

        self.trace.emit(
            run_id,
            "run_failed",
            {"reason": "max_agent_steps_exceeded"},
        )
        raise RuntimeError(
            f"Agent 超过最大循环次数 {self.settings.max_agent_steps}，已停止以避免失控。"
        )

    def _build_payload(self, input_items: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "instructions": DEVELOPER_INSTRUCTIONS,
            "input": input_items,
            "tools": self.tools.schemas(),
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "product_analysis",
                    "strict": True,
                    "schema": ANSWER_SCHEMA,
                }
            },
            "store": False,
        }
        if self.settings.reasoning_effort:
            payload["reasoning"] = {"effort": self.settings.reasoning_effort}
        if self.settings.temperature is not None:
            payload["temperature"] = self.settings.temperature
        if self.settings.top_p is not None:
            payload["top_p"] = self.settings.top_p
        return payload
