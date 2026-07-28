from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

from .types import Chunk


ASCII_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")
CHINESE_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def tokenize(text: str) -> list[str]:
    """面向中英混合资料的轻量分词：英文词 + 中文单字/双字。"""
    lowered = text.lower()
    tokens = ASCII_WORD_RE.findall(lowered)
    for run in CHINESE_RUN_RE.findall(lowered):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    closing = text.find("\n---\n", 4)
    if closing == -1:
        return {}, text
    metadata: dict[str, str] = {}
    for line in text[4:closing].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, text[closing + 5 :]


def split_sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_heading = "正文"
    current_lines: list[str] = []
    for line in body.splitlines():
        heading_match = HEADING_RE.match(line)
        if heading_match:
            if any(item.strip() for item in current_lines):
                sections.append((current_heading, current_lines))
            current_heading = heading_match.group(2)
            current_lines = []
        else:
            current_lines.append(line)
    if any(item.strip() for item in current_lines):
        sections.append((current_heading, current_lines))
    return [
        (heading, "\n".join(lines).strip())
        for heading, lines in sections
        if "\n".join(lines).strip()
    ]


def window_text(text: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    windows: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        windows.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return [window for window in windows if window]


class KnowledgeBase:
    def __init__(self, directory: Path):
        self.directory = directory
        self.chunks = self._load_chunks()
        self._term_frequencies = [Counter(tokenize(chunk.text)) for chunk in self.chunks]
        self._document_frequency = Counter(
            token
            for frequencies in self._term_frequencies
            for token in frequencies.keys()
        )
        self._average_length = (
            sum(sum(frequencies.values()) for frequencies in self._term_frequencies)
            / max(len(self._term_frequencies), 1)
        )

    def _load_chunks(self) -> list[Chunk]:
        chunks: list[Chunk] = []
        for path in sorted(self.directory.glob("*.md")):
            metadata, body = parse_front_matter(path.read_text(encoding="utf-8"))
            source_id = metadata.get("source_id", path.stem)
            title = metadata.get("title", path.stem)
            roles = tuple(
                role.strip()
                for role in metadata.get("access_roles", "employee,pm,admin").split(",")
                if role.strip()
            )
            version = metadata.get("version", "unknown")
            sequence = 0
            for heading, section_text in split_sections(body):
                for window in window_text(section_text):
                    sequence += 1
                    chunks.append(
                        Chunk(
                            chunk_id=f"{source_id}::{sequence:03d}",
                            source_id=source_id,
                            title=title,
                            heading=heading,
                            text=f"## {heading}\n{window}",
                            access_roles=roles,
                            version=version,
                            path=str(path),
                        )
                    )
        return chunks

    def search(self, query: str, role: str = "employee", top_k: int = 4) -> list[Chunk]:
        query_terms = Counter(tokenize(query))
        if not query_terms:
            return []
        scored: list[Chunk] = []
        total_documents = max(len(self.chunks), 1)
        k1 = 1.5
        b = 0.75
        for index, chunk in enumerate(self.chunks):
            if role not in chunk.access_roles:
                continue
            frequencies = self._term_frequencies[index]
            document_length = max(sum(frequencies.values()), 1)
            score = 0.0
            for token, query_count in query_terms.items():
                term_frequency = frequencies.get(token, 0)
                if not term_frequency:
                    continue
                document_frequency = self._document_frequency[token]
                inverse_frequency = math.log(
                    1
                    + (total_documents - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                denominator = term_frequency + k1 * (
                    1 - b + b * document_length / max(self._average_length, 1)
                )
                score += (
                    inverse_frequency
                    * term_frequency
                    * (k1 + 1)
                    / denominator
                    * query_count
                )
            title_overlap = set(tokenize(chunk.title + chunk.heading)) & set(query_terms)
            score += 0.8 * len(title_overlap)
            if score > 0:
                scored.append(replace(chunk, score=round(score, 4)))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]
