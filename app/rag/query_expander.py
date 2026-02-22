from __future__ import annotations

import logging
import re

from app.rag.llm_client import LLMClient

logger = logging.getLogger(__name__)

_MAX_TARGET_COUNT = 8
_LEADING_BULLET_RE = re.compile(r"^(?:\d+[\).:-]?|[-*•])\s*")
_WHITESPACE_RE = re.compile(r"\s+")


class QueryExpander:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def expand(self, question: str, target_count: int) -> list[str]:
        base_query = self._normalize_query(question)
        if not base_query:
            return []

        capped_count = self._clamp_target_count(target_count)
        if capped_count == 1:
            return [base_query]

        prompt = (
            "Generate concise retrieval-friendly rewrites for this question.\n"
            "Preserve the original meaning and user intent exactly; only rewrite "
            "wording "
            "or keywords for search coverage.\n"
            "Do not broaden, narrow, or change topic.\n"
            f"Question: {base_query}\n"
            f"Return up to {capped_count - 1} alternatives, one per line, no prose."
        )
        logger.debug(
            "Expanding query (target_count=%d): '%s'",
            capped_count,
            base_query,
        )
        try:
            raw = self._client.generate(prompt)
        except Exception:
            logger.exception("Query expansion failed, falling back to original query")
            return [base_query]

        logger.debug("Raw expansion response: %r", raw[:500] if raw else "(empty)")
        parsed = self._parse_output(raw)
        deduped = self._dedupe_stable([base_query, *parsed])
        if not deduped:
            return [base_query]
        result = deduped[:capped_count]
        logger.debug(
            "Expanded to %d queries: %s",
            len(result),
            ", ".join(f"'{q}'" for q in result),
        )
        return result

    @staticmethod
    def _normalize_query(value: str) -> str:
        return _WHITESPACE_RE.sub(" ", value).strip()

    @staticmethod
    def _clamp_target_count(value: int) -> int:
        return max(1, min(_MAX_TARGET_COUNT, int(value)))

    def _parse_output(self, raw: str) -> list[str]:
        stripped = raw.strip()
        if not stripped:
            return []

        candidates: list[str] = []
        for line in stripped.splitlines():
            cleaned = _LEADING_BULLET_RE.sub("", line).strip().strip('"').strip("'")
            normalized = self._normalize_query(cleaned)
            if normalized:
                candidates.append(normalized)

        if candidates:
            return candidates

        fallback = [self._normalize_query(part) for part in stripped.split(";")]
        return [part for part in fallback if part]

    def _dedupe_stable(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = self._normalize_query(value)
            if not normalized:
                continue
            dedupe_key = normalized.casefold()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            result.append(normalized)
        return result
