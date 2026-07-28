from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Protocol

from .config import Settings


class ResponsesClient(Protocol):
    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


def extract_output_text(response: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and "text" in content:
                texts.append(str(content["text"]))
            if content.get("type") == "refusal":
                raise RuntimeError(f"模型拒绝了请求：{content.get('refusal', '')}")
    return "\n".join(texts)


class OpenAIResponsesClient:
    """直接用 HTTP 调 Responses API，便于学习 API、鉴权和 JSON。"""

    def __init__(self, api_key: str, api_url: str, timeout_seconds: int = 90):
        if not api_key:
            raise ValueError(
                "MODEL_PROVIDER=openai 时必须设置 OPENAI_API_KEY；"
                "新手可先使用默认 mock 模式。"
            )
        self.api_key = api_key
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"模型 API 返回 HTTP {exc.code}：{details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接模型 API：{exc.reason}") from exc


def _latest_user_text(input_items: list[dict[str, Any]]) -> str:
    for item in reversed(input_items):
        if item.get("role") == "user":
            return str(item.get("content", ""))
    return ""


def _called_tool(input_items: list[dict[str, Any]], name: str) -> bool:
    return any(
        item.get("type") == "function_call" and item.get("name") == name
        for item in input_items
    )


def _tool_outputs(input_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for item in input_items:
        if item.get("type") != "function_call_output":
            continue
        try:
            parsed = json.loads(str(item.get("output", "{}")))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            outputs.append(parsed)
    return outputs


def _parse_rice_arguments(text: str) -> dict[str, Any] | None:
    patterns = {
        "reach": r"\breach\s*[:=：]\s*(\d+)",
        "impact": r"\bimpact\s*[:=：]\s*(\d+(?:\.\d+)?)",
        "confidence": r"\bconfidence\s*[:=：]\s*(\d+(?:\.\d+)?)",
        "effort": r"\beffort\s*[:=：]\s*(\d+(?:\.\d+)?)",
    }
    values: dict[str, Any] = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        values[name] = int(match.group(1)) if name == "reach" else float(match.group(1))
    return values


def _source_blocks(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r'<SOURCE source_id="([^"]+)"[^>]*>\s*(.*?)\s*</SOURCE>',
        re.DOTALL,
    )
    return [(match.group(1), match.group(2)) for match in pattern.finditer(text)]


def _evidence_lines(body: str) -> list[str]:
    unsafe_markers = ("忽略系统", "泄露", "api key", "隐藏指令")
    lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip().lstrip("-*").strip()
        if not line or line.startswith("#"):
            continue
        if any(marker in line.lower() for marker in unsafe_markers):
            continue
        if len(line) >= 8:
            lines.append(line)
    return lines


class MockResponsesClient:
    """离线确定性模型，用于先学系统流程、测试和评测。"""

    def __init__(self):
        self.sequence = 0

    def _response(self, output: list[dict[str, Any]]) -> dict[str, Any]:
        self.sequence += 1
        return {
            "id": f"mock_response_{self.sequence}",
            "status": "completed",
            "output": output,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
        }

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        time.sleep(0.005)
        input_items = list(payload.get("input", []))
        user_text = _latest_user_text(input_items)
        rice_arguments = _parse_rice_arguments(user_text)
        if rice_arguments and not _called_tool(
            input_items,
            "calculate_priority_score",
        ):
            return self._response(
                [
                    {
                        "type": "function_call",
                        "id": f"mock_fc_{self.sequence + 1}",
                        "call_id": f"mock_call_{self.sequence + 1}",
                        "name": "calculate_priority_score",
                        "arguments": json.dumps(rice_arguments),
                    }
                ]
            )

        if "保存" in user_text and not _called_tool(
            input_items,
            "save_analysis_draft",
        ):
            return self._response(
                [
                    {
                        "type": "function_call",
                        "id": f"mock_fc_{self.sequence + 1}",
                        "call_id": f"mock_call_{self.sequence + 1}",
                        "name": "save_analysis_draft",
                        "arguments": json.dumps(
                            {
                                "title": "产品需求分析草稿",
                                "summary": "根据当前证据形成的教学版分析草稿。",
                                "priority": "暂定，需结合缺失数据复核",
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            )

        answer = self._build_answer(user_text, input_items)
        return self._response(
            [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(answer, ensure_ascii=False),
                            "annotations": [],
                        }
                    ],
                }
            ]
        )

    def _build_answer(
        self,
        user_text: str,
        input_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        blocks = _source_blocks(user_text)
        facts: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        for source_id, body in blocks:
            for evidence in _evidence_lines(body)[:2]:
                facts.append(
                    {
                        "statement": evidence,
                        "source_ids": [source_id],
                    }
                )
                citations.append(
                    {
                        "source_id": source_id,
                        "evidence": evidence[:180],
                    }
                )
                if len(facts) >= 3:
                    break
            if len(facts) >= 3:
                break

        outputs = _tool_outputs(input_items)
        rice_output = next(
            (item for item in outputs if "rice_score" in item),
            None,
        )
        save_output = next(
            (
                item
                for item in outputs
                if item.get("tool") == "save_analysis_draft"
            ),
            None,
        )
        if rice_output:
            priority_level = f"RICE 暂定分数 {rice_output['rice_score']}"
            priority_basis = (
                "由确定性工具按 (reach × impact × confidence) ÷ effort 计算。"
            )
            missing_data: list[str] = ["仍需验证四项输入的数据口径"]
        else:
            priority_level = "暂不正式排序"
            priority_basis = "当前证据不足以支持正式优先级决策。"
            missing_data = ["reach", "impact", "confidence", "effort"]

        if save_output and save_output.get("status") == "saved":
            save_note = f"草稿已在批准后保存：{save_output.get('path', '')}"
        elif save_output and save_output.get("status") == "denied":
            save_note = "写操作未获人工批准，草稿没有保存。"
        else:
            save_note = ""

        if facts:
            summary = "已根据当前可访问证据形成初步分析。"
            if save_note:
                summary += save_note
            status = "completed"
            questions = ["目标用户范围与正式决策负责人是谁？"]
            confidence = 0.72
        else:
            summary = "当前没有检索到足以回答核心问题的可访问证据。"
            if save_note:
                summary += save_note
            status = "needs_clarification"
            questions = ["请补充客户原始反馈或指定可查询的知识资料。"]
            confidence = 0.2

        first_source = facts[0]["source_ids"][0] if facts else "无"
        return {
            "status": status,
            "summary": summary,
            "facts": facts,
            "inferences": (
                [
                    {
                        "statement": "现有反馈可能指向提升数据处理效率的需求。",
                        "basis": f"基于检索证据 {first_source}，仍需用户研究验证。",
                        "validation_status": "hypothesis",
                    }
                ]
                if facts
                else []
            ),
            "proposals": (
                [
                    {
                        "proposal": "先用小范围原型验证高频任务，再决定是否进入正式开发。",
                        "risk": "样本量或使用场景不足可能导致错误优先级。",
                        "decision_status": "temporary",
                    }
                ]
                if facts
                else []
            ),
            "priority": {
                "level": priority_level,
                "basis": priority_basis,
                "missing_data": missing_data,
            },
            "citations": citations,
            "questions": questions,
            "confidence": confidence,
        }


def build_client(settings: Settings) -> ResponsesClient:
    if settings.provider == "mock":
        return MockResponsesClient()
    if settings.provider == "openai":
        return OpenAIResponsesClient(settings.api_key, settings.api_url)
    raise ValueError(f"不支持的 MODEL_PROVIDER：{settings.provider}")
