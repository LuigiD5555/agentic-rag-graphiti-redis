"""
Math Specialist — extracts mathematical structure from a query.

Model: google/flan-t5-base (~990MB) — same model as FactExtractor,
       shared class-level load (no double memory cost when both are registered).
Input:  state.user_query + state.perception (needs_math=True)
Output: state.specialists.math_result (structured dict or computed value)

Two stages:
  1. Structure extraction — identify problem type, variables, operation
  2. Computation — attempt to evaluate with sympy if available, else Python eval

Only runs when state.perception.needs_math == True.

Fallback: regex-based number extraction + basic arithmetic.
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

_EXTRACT_PROMPT = (
    "Extract the mathematical structure from this text. "
    "Identify: problem_type (percentage/arithmetic/algebra/other), "
    "numbers (list of numeric values found), operation (what to compute), "
    "result if computable.\n"
    "Text: {query}\n"
    "Structure:"
)

_NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:\s*%)?")


def _try_sympy(expression: str) -> Optional[float]:
    try:
        import sympy
        result = sympy.sympify(expression.replace(",", "."))
        return float(result)
    except Exception:
        return None


def _try_eval(expression: str) -> Optional[float]:
    """Safe eval restricted to numeric expressions only."""
    safe_expr = re.sub(r"[^\d+\-*/(). ]", "", expression)
    if not safe_expr.strip():
        return None
    try:
        result = eval(safe_expr, {"__builtins__": {}})  # noqa: S307
        return float(result)
    except Exception:
        return None


class MathSpecialist(BaseSpecialist):
    name = "math_specialist"
    model_id = "google/flan-t5-base"
    # Shared with FactExtractor — if FactExtractor loaded it first, reuse
    _model: ClassVar[Optional[Any]] = None
    _model_loaded: ClassVar[bool] = False

    @classmethod
    def _load_model(cls) -> Any:
        # Reuse FactExtractor's model if already loaded (same model_id)
        from swarm_rag.specialists.fact_extractor import FactExtractor
        if FactExtractor._model is not None:
            cls._model = FactExtractor._model
            return cls._model
        from transformers import pipeline
        return pipeline(
            "text2text-generation",
            model=cls.model_id,
            max_new_tokens=_MAX_NEW_TOKENS,
        )

    async def run(self, state: BlackboardState) -> BlackboardState:
        if not state.perception.needs_math:
            return state

        if not self._model_loaded:
            self.__class__.load()

        t0 = time.monotonic()

        # Try model-based extraction
        if self._model is not None:
            prompt = _EXTRACT_PROMPT.format(query=state.user_query)
            try:
                raw = await self._run_in_executor(
                    lambda p: self._model(p)[0]["generated_text"], prompt
                )
                result = self._interpret(raw, state.user_query)
                state.specialists.math_result = result
                logger.info("MathSpecialist: result=%s", result)
            except Exception as exc:
                logger.warning("MathSpecialist model failed: %s — using regex", exc)
                state.specialists.math_result = self._regex_compute(state.user_query)
        else:
            state.specialists.math_result = self._regex_compute(state.user_query)

        self._record(state, round((time.monotonic() - t0) * 1000, 2))
        return state

    def _fallback(self, state: BlackboardState) -> BlackboardState:
        state.specialists.math_result = self._regex_compute(state.user_query)
        return state

    def _interpret(self, raw: str, query: str) -> Any:
        """Try to compute a result from the model's structured output."""
        # Look for numbers in model output and attempt computation
        numbers = [float(n.replace(",", ".").rstrip("%")) for n in _NUMBER_RE.findall(raw)]
        if not numbers:
            numbers = [float(n.replace(",", ".").rstrip("%")) for n in _NUMBER_RE.findall(query)]

        # Percentage pattern: "X% of Y"
        pct_match = re.search(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:of|de|del)\s*(\d+(?:[.,]\d+)?)", query, re.I)
        if pct_match:
            pct = float(pct_match.group(1).replace(",", "."))
            base = float(pct_match.group(2).replace(",", "."))
            return round(pct / 100 * base, 4)

        # Try sympy on the raw output
        result = _try_sympy(raw) or _try_eval(raw)
        if result is not None:
            return result

        # Return extracted numbers as the "result" if we can't compute
        return {"numbers_found": numbers, "raw_structure": raw[:200]}

    @staticmethod
    def _regex_compute(query: str) -> Any:
        """Regex-only fallback: handle percentage and basic arithmetic."""
        pct_match = re.search(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:of|de|del)\s*(\d+(?:[.,]\d+)?)", query, re.I)
        if pct_match:
            pct = float(pct_match.group(1).replace(",", "."))
            base = float(pct_match.group(2).replace(",", "."))
            return round(pct / 100 * base, 4)

        numbers = [float(n.replace(",", ".").rstrip("%")) for n in _NUMBER_RE.findall(query)]
        return {"numbers_found": numbers} if numbers else None
