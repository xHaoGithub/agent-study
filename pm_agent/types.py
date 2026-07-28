from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_id: str
    title: str
    heading: str
    text: str
    access_roles: tuple[str, ...]
    version: str
    path: str
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolExecution:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    approved: bool
    risk: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    run_id: str
    answer: dict[str, Any]
    retrieved: list[Chunk] = field(default_factory=list)
    tool_executions: list[ToolExecution] = field(default_factory=list)
    model: str = ""
    provider: str = ""
    prompt_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "answer": self.answer,
            "retrieved": [chunk.to_dict() for chunk in self.retrieved],
            "tool_executions": [item.to_dict() for item in self.tool_executions],
            "model": self.model,
            "provider": self.provider,
            "prompt_version": self.prompt_version,
        }
