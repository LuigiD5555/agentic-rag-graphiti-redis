"""
Code Specialist — detects code language, task type, symbols, and potential issues.

Model: Salesforce/codet5-small (~120MB, seq2seq for code)
Input:  state.user_query + state.perception.needs_code (must be True)
Output: state.specialists.code_analysis (dict)

Extracts:
  - language: detected programming language
  - task_type: 'debug' | 'explain' | 'refactor' | 'generate' | 'review'
  - symbols: function/class/variable names mentioned
  - issues: potential bugs or code smells mentioned
  - tool_hint: suggested MCP action ('search_file', 'run_tests', 'diff')

Fallback: regex-based extraction (no model needed).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, ClassVar, Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState
from swarm_rag.specialists.base_specialist import BaseSpecialist

logger = logging.getLogger(__name__)

_MAX_NEW_TOKENS = 150

_PROMPT_TEMPLATE = (
    "Analyze this code-related question. "
    "Identify: programming language, task type (debug/explain/refactor/generate/review), "
    "symbols mentioned (functions, classes, variables), and any issues described.\n"
    "Question: {query}\n"
    "Analysis:"
)

# Regex patterns for fallback
_LANG_PATTERNS = {
    "Python": re.compile(r"\b(python|py|def |class |import |\.py)\b", re.I),
    "JavaScript": re.compile(r"\b(javascript|js|typescript|ts|node\.?js|react|vue)\b", re.I),
    "Java": re.compile(r"\b(java|\.java|spring|maven|gradle)\b", re.I),
    "Go": re.compile(r"\b(golang|\.go|goroutine)\b", re.I),
    "Rust": re.compile(r"\b(rust|\.rs|cargo)\b", re.I),
    "SQL": re.compile(r"\b(sql|query|select |insert |update |delete )\b", re.I),
}

_TASK_PATTERNS = {
    "debug": re.compile(r"\b(bug|error|fix|crash|traceback|excepci[oó]n|falla|no funciona)\b", re.I),
    "explain": re.compile(r"\b(explica|qu[eé] hace|c[oó]mo funciona|explain|what does)\b", re.I),
    "refactor": re.compile(r"\b(refactor|mejora|optimiza|limpia|simplifica)\b", re.I),
    "generate": re.compile(r"\b(implementa|crea|escribe|genera|create|write|implement)\b", re.I),
    "review": re.compile(r"\b(revisa|review|analiza|verifica|check)\b", re.I),
}

_SYMBOL_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:Service|Manager|Repository|Controller|Handler|Model|View|Client|Factory)|[a-z_]+\(\))\b")
_ISSUE_PATTERNS = re.compile(r"\b(bug|error|excepci[oó]n|falla|crash|null|undefined|timeout|memory leak|race condition)\b", re.I)

_TOOL_HINTS = {
    "debug": "search_file",
    "review": "diff",
    "generate": "run_tests",
    "explain": "search_file",
    "refactor": "diff",
}


class CodeSpecialist(BaseSpecialist):
    name = "code_specialist"
    model_id = "Salesforce/codet5-small"
    _model: ClassVar[Optional[Any]] = None
    _model_loaded: ClassVar[bool] = False

    @classmethod
    def _load_model(cls) -> Any:
        from transformers import pipeline
        return pipeline(
            "text2text-generation",
            model=cls.model_id,
            max_new_tokens=_MAX_NEW_TOKENS,
        )

    async def run(self, state: BlackboardState) -> BlackboardState:
        if not state.perception.needs_code:
            return state

        if not self._model_loaded:
            self.__class__.load()

        t0 = time.monotonic()

        if self._model is not None:
            prompt = _PROMPT_TEMPLATE.format(query=state.user_query)
            try:
                raw = await self._run_in_executor(
                    lambda prompt_text: self._model(prompt_text)[0]["generated_text"], prompt
                )
                analysis = self._merge_with_regex(raw, state.user_query)
            except Exception as exc:
                logger.warning("CodeSpecialist model failed: %s — using regex", exc)
                analysis = self._regex_analysis(state.user_query)
        else:
            analysis = self._regex_analysis(state.user_query)

        state.specialists.code_analysis = analysis
        logger.info(
            "CodeSpecialist: lang=%s task=%s symbols=%d issues=%d",
            analysis.get("language"), analysis.get("task_type"),
            len(analysis.get("symbols", [])), len(analysis.get("issues", [])),
        )
        self._record(state, round((time.monotonic() - t0) * 1000, 2))
        return state

    def _fallback(self, state: BlackboardState) -> BlackboardState:
        state.specialists.code_analysis = self._regex_analysis(state.user_query)
        return state

    def _merge_with_regex(self, model_output: str, query: str) -> dict:
        """Use model output where available, regex to fill gaps."""
        regex = self._regex_analysis(query)
        # Model output may contain useful additional info
        combined_text = model_output + " " + query
        symbols = list({*regex["symbols"], *_SYMBOL_RE.findall(combined_text)})
        return {**regex, "symbols": symbols[:10], "model_raw": model_output[:200]}

    @staticmethod
    def _regex_analysis(query: str) -> dict:
        # Detect language
        language = "unknown"
        for lang, pattern in _LANG_PATTERNS.items():
            if pattern.search(query):
                language = lang
                break

        # Detect task type
        task_type = "explain"
        for task, pattern in _TASK_PATTERNS.items():
            if pattern.search(query):
                task_type = task
                break

        # Extract symbols and issues
        symbols = list(set(_SYMBOL_RE.findall(query)))[:8]
        issues = list(set(_ISSUE_PATTERNS.findall(query)))[:5]

        return {
            "language": language,
            "task_type": task_type,
            "symbols": symbols,
            "issues": issues,
            "tool_hint": _TOOL_HINTS.get(task_type, "search_file"),
        }
