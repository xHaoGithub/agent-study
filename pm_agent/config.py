from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """读取简单的 KEY=VALUE 配置；不覆盖终端里已经设置的环境变量。"""
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


def _optional_float(name: str) -> float | None:
    value = os.getenv(name, "").strip()
    return float(value) if value else None


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    provider: str = "mock"
    model: str = "gpt-5.6"
    api_key: str = ""
    api_url: str = "https://api.openai.com/v1/responses"
    reasoning_effort: str = "low"
    temperature: float | None = None
    top_p: float | None = None
    top_k: int = 4
    max_agent_steps: int = 4

    @property
    def knowledge_dir(self) -> Path:
        return self.project_root / "knowledge"

    @property
    def trace_path(self) -> Path:
        return self.project_root / "logs" / "traces.jsonl"

    @property
    def draft_dir(self) -> Path:
        return self.project_root / "artifacts" / "drafts"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            provider=os.getenv("MODEL_PROVIDER", "mock").strip().lower(),
            model=os.getenv("OPENAI_MODEL", "gpt-5.6").strip(),
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            api_url=os.getenv(
                "OPENAI_RESPONSES_URL",
                "https://api.openai.com/v1/responses",
            ).strip(),
            reasoning_effort=os.getenv("MODEL_REASONING_EFFORT", "low").strip(),
            temperature=_optional_float("MODEL_TEMPERATURE"),
            top_p=_optional_float("MODEL_TOP_P"),
            top_k=int(os.getenv("RAG_TOP_K", "4")),
            max_agent_steps=int(os.getenv("MAX_AGENT_STEPS", "4")),
        )

    def with_provider(self, provider: str) -> "Settings":
        return replace(self, provider=provider)
