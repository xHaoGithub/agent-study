from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]
ApprovalCallback = Callable[[str, dict[str, Any]], bool]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def api_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "strict": True,
        }


def calculate_priority_score(arguments: dict[str, Any]) -> dict[str, Any]:
    reach = int(arguments["reach"])
    impact = float(arguments["impact"])
    confidence = float(arguments["confidence"])
    effort = float(arguments["effort"])
    if reach < 0:
        raise ValueError("reach 不能小于 0")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence 必须在 0 到 1 之间")
    if effort <= 0:
        raise ValueError("effort 必须大于 0")
    score = reach * impact * confidence / effort
    return {
        "tool": "calculate_priority_score",
        "formula": "(reach × impact × confidence) ÷ effort",
        "rice_score": round(score, 2),
        "inputs": {
            "reach": reach,
            "impact": impact,
            "confidence": confidence,
            "effort": effort,
        },
    }


def _safe_filename(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", value).strip("-")
    return normalized[:48] or "analysis"


def build_save_handler(draft_dir: Path) -> ToolHandler:
    def save_analysis_draft(arguments: dict[str, Any]) -> dict[str, Any]:
        draft_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        filename = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{_safe_filename(arguments['title'])}.json"
        target = draft_dir / filename
        payload = {
            "created_at": now.isoformat(),
            "title": str(arguments["title"]),
            "summary": str(arguments["summary"]),
            "priority": str(arguments["priority"]),
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "tool": "save_analysis_draft",
            "status": "saved",
            "path": str(target),
        }

    return save_analysis_draft


class ToolRegistry:
    def __init__(self, draft_dir: Path):
        strict_object = {
            "type": "object",
            "additionalProperties": False,
        }
        self._tools = {
            "calculate_priority_score": ToolSpec(
                name="calculate_priority_score",
                description=(
                    "使用 RICE 公式计算暂定优先级分数。只有四个输入均有明确依据时使用；"
                    "confidence 取 0 到 1，effort 必须大于 0。"
                ),
                risk="read",
                parameters={
                    **strict_object,
                    "properties": {
                        "reach": {"type": "integer", "minimum": 0},
                        "impact": {"type": "number", "minimum": 0},
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "effort": {"type": "number", "exclusiveMinimum": 0},
                    },
                    "required": ["reach", "impact", "confidence", "effort"],
                },
                handler=calculate_priority_score,
            ),
            "save_analysis_draft": ToolSpec(
                name="save_analysis_draft",
                description=(
                    "把分析草稿保存到本地文件。该工具会改变外部状态，必须仅在用户明确"
                    "要求保存时调用，并接受应用层人工审批。"
                ),
                risk="write",
                parameters={
                    **strict_object,
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "priority": {"type": "string"},
                    },
                    "required": ["title", "summary", "priority"],
                },
                handler=build_save_handler(draft_dir),
            ),
        }

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.api_schema() for tool in self._tools.values()]

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise ValueError(f"未知工具：{name}")
        return self._tools[name]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        approval_callback: ApprovalCallback | None = None,
    ) -> tuple[dict[str, Any], bool, str]:
        tool = self.get(name)
        approved = tool.risk != "write"
        if tool.risk == "write":
            approved = bool(
                approval_callback and approval_callback(tool.name, arguments)
            )
            if not approved:
                return (
                    {
                        "tool": tool.name,
                        "status": "denied",
                        "message": "人工未批准写操作，未产生文件。",
                    },
                    False,
                    tool.risk,
                )
        try:
            return tool.handler(arguments), approved, tool.risk
        except (KeyError, TypeError, ValueError) as exc:
            return (
                {
                    "tool": tool.name,
                    "status": "error",
                    "error": str(exc),
                },
                approved,
                tool.risk,
            )
