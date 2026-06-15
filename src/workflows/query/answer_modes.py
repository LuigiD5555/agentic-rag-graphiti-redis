"""Runtime-configurable answer modes for RAG responses."""


import json
import os
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional, Literal

from pydantic import BaseModel, Field, ValidationError
from pydantic.config import ConfigDict

from src.conf import settings
from src.backends.storage.sqlite.manager import get_sqlite_manager
from src.workflows.query.audit import get_logger

log = get_logger(__name__)

_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {"mtime": None, "data": None}

DEFAULT_MODES: Dict[str, Any] = {
    "default_mode": "detailed",
    "modes": {
        "detailed": {
            "description": "Respuesta detallada y estructurada.",
            "instruction": (
                "Provide detailed, well-structured answers; prefer depth over brevity. "
                "Use bullet points or short sections when helpful. "
                "When multiple relevant sources exist, synthesize them."
            ),
            "instruction_by_lang": {
                "es": (
                    "Ofrece respuestas detalladas y bien estructuradas; prioriza la profundidad "
                    "sobre la brevedad. Usa viñetas o secciones cortas cuando sea útil. "
                    "Cuando haya varias fuentes relevantes, sintetízalas."
                )
            },
            "triggers": [
                "detallado",
                "en detalle",
                "profundo",
                "extenso",
                "amplio",
                "detailed",
                "in detail",
                "deep",
                "comprehensive",
            ],
            "persist_triggers": [
                "modo",
                "por defecto",
                "a partir de ahora",
                "desde ahora",
                "siempre",
                "default",
            ],
        },
        "concise": {
            "description": "Respuesta breve y directa.",
            "instruction": (
                "Answer concisely. Use at most 3-6 bullet points and avoid secondary details."
            ),
            "instruction_by_lang": {
                "es": (
                    "Responde de forma concisa. Usa como máximo 3-6 viñetas y evita detalles secundarios."
                )
            },
            "triggers": [
                "conciso",
                "breve",
                "resumen",
                "resumido",
                "en pocas palabras",
                "tldr",
                "short",
                "brief",
                "concise",
                "summarize",
                "summary",
            ],
            "persist_triggers": [
                "modo",
                "por defecto",
                "a partir de ahora",
                "desde ahora",
                "siempre",
                "default",
            ],
        },
    },
}


class PreanalysisConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: Optional[bool] = None
    prompt: Optional[str] = None
    prompt_es: Optional[str] = None
    include_context: Optional[bool] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    model: Optional[str] = None


class PipelineStepModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["preanalysis", "answer"]
    config: Optional[Dict[str, Any]] = None


class AnswerModeConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = None
    instruction: Optional[str] = None
    instruction_by_lang: Optional[Dict[str, str]] = None
    triggers: Optional[list[str]] = None
    persist_triggers: Optional[list[str]] = None
    preanalysis: Optional[PreanalysisConfigModel] = None
    pipeline: Optional[list[PipelineStepModel]] = None


class AnswerModesConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_mode: Optional[str] = None
    modes: Optional[Dict[str, AnswerModeConfigModel]] = None


def _settings_path() -> Path:
    configured = getattr(settings, "USER_SETTINGS_FILE", "data/settings.json")
    path = Path(str(configured))
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    return path


def _load_settings_json() -> Dict[str, Any]:
    path = _settings_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        log.debug("Failed to read settings.json: %s", exc)
        return {}


def _write_settings_json(data: Dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def get_answer_modes(force_reload: bool = False) -> Dict[str, Any]:
    path = _settings_path()
    mtime = path.stat().st_mtime if path.exists() else None
    with _LOCK:
        if not force_reload and _CACHE["data"] is not None and _CACHE["mtime"] == mtime:
            return deepcopy(_CACHE["data"])

        raw_settings = _load_settings_json()
        raw_modes = raw_settings.get("ANSWER_MODES", {})
        merged = deepcopy(DEFAULT_MODES)

        if isinstance(raw_modes, dict):
            if isinstance(raw_modes.get("default_mode"), str):
                merged["default_mode"] = raw_modes["default_mode"]
            if isinstance(raw_modes.get("modes"), dict):
                merged_modes = merged.setdefault("modes", {})
                for key, value in raw_modes["modes"].items():
                    if isinstance(value, dict):
                        existing = merged_modes.get(key, {})
                        merged_modes[key] = {**existing, **value}

        merged = _validate_answer_modes(merged)
        _CACHE["data"] = deepcopy(merged)
        _CACHE["mtime"] = mtime
        return deepcopy(merged)


def update_answer_modes(payload: Dict[str, Any], merge: bool = True) -> Dict[str, Any]:
    with _LOCK:
        settings_data = _load_settings_json()
        current = settings_data.get("ANSWER_MODES", {})

        if merge:
            updated = deepcopy(current) if isinstance(current, dict) else {}
            for key, value in payload.items():
                if key == "modes" and isinstance(value, dict):
                    existing_modes = updated.get("modes", {})
                    if not isinstance(existing_modes, dict):
                        existing_modes = {}
                    for mode_name, mode_data in value.items():
                        if not isinstance(mode_data, dict):
                            continue
                        existing_mode = existing_modes.get(mode_name, {})
                        if not isinstance(existing_mode, dict):
                            existing_mode = {}
                        existing_modes[mode_name] = {**existing_mode, **mode_data}
                    updated["modes"] = existing_modes
                else:
                    updated[key] = value
        else:
            updated = payload

        validated = _validate_answer_modes(updated)
        settings_data["ANSWER_MODES"] = validated
        _write_settings_json(settings_data)

        _CACHE["data"] = None
        _CACHE["mtime"] = None

    return get_answer_modes(force_reload=True)


def get_answer_mode(mode_name: str) -> Optional[Dict[str, Any]]:
    modes = get_answer_modes().get("modes", {})
    mode = modes.get(mode_name)
    return deepcopy(mode) if isinstance(mode, dict) else None


def upsert_answer_mode(mode_name: str, config: Dict[str, Any], merge: bool = True) -> Dict[str, Any]:
    payload = {"modes": {mode_name: config}}
    updated = update_answer_modes(payload=payload, merge=merge)
    return updated.get("modes", {}).get(mode_name, {})


def delete_answer_mode(mode_name: str) -> Dict[str, Any]:
    with _LOCK:
        settings_data = _load_settings_json()
        current = settings_data.get("ANSWER_MODES", {})
        modes = current.get("modes", {})
        if isinstance(modes, dict) and mode_name in modes:
            modes.pop(mode_name)
        current["modes"] = modes

        default_mode = current.get("default_mode")
        if default_mode == mode_name:
            if isinstance(modes, dict) and "detailed" in modes:
                current["default_mode"] = "detailed"
            elif isinstance(modes, dict) and modes:
                current["default_mode"] = next(iter(modes.keys()))
            else:
                current["default_mode"] = "detailed"

        validated = _validate_answer_modes(current)
        settings_data["ANSWER_MODES"] = validated
        _write_settings_json(settings_data)

        _CACHE["data"] = None
        _CACHE["mtime"] = None

    return get_answer_modes(force_reload=True)


def resolve_mode(question: str, session_id: Optional[str]) -> str:
    modes_config = get_answer_modes()
    modes = modes_config.get("modes", {})
    default_mode = modes_config.get("default_mode", "detailed")

    normalized = question.lower()
    explicit_mode = None
    persist = False

    for mode_name, mode_data in modes.items():
        if not isinstance(mode_data, dict):
            continue
        triggers = mode_data.get("triggers") or []
        if any(token in normalized for token in triggers):
            explicit_mode = mode_name
            persist = any(
                token in normalized for token in (mode_data.get("persist_triggers") or [])
            )
            break

    if explicit_mode:
        if session_id and persist:
            _persist_mode(session_id, explicit_mode)
        return explicit_mode

    if session_id:
        preferred = _get_session_mode(session_id)
        if isinstance(preferred, str) and preferred in modes:
            return preferred

    return default_mode


def get_mode_config(mode_name: str) -> Dict[str, Any]:
    modes = get_answer_modes().get("modes", {})
    return deepcopy(modes.get(mode_name, {}))


def get_mode_instruction(mode_config: Dict[str, Any], language: str) -> Optional[str]:
    by_lang = mode_config.get("instruction_by_lang")
    if isinstance(by_lang, dict) and isinstance(by_lang.get(language), str):
        return by_lang[language]
    instruction = mode_config.get("instruction")
    if isinstance(instruction, str):
        return instruction
    return None


def _validate_answer_modes(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        model = AnswerModesConfigModel.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid ANSWER_MODES config: {exc}") from exc

    validated = model.model_dump(exclude_none=True)
    modes = validated.get("modes") or {}
    if not modes:
        validated["modes"] = deepcopy(DEFAULT_MODES["modes"])
    if "default_mode" not in validated:
        validated["default_mode"] = DEFAULT_MODES["default_mode"]
    if validated["default_mode"] not in validated.get("modes", {}):
        if "detailed" in validated["modes"]:
            validated["default_mode"] = "detailed"
        else:
            validated["default_mode"] = next(iter(validated["modes"].keys()))
    return validated


def _persist_mode(session_id: str, mode_name: str) -> None:
    try:
        session_repo = get_sqlite_manager().get_session_repository()
        session_repo.update_session(
            session_id=session_id,
            preferred_answer_style=mode_name,
            now_ts=int(time.time()),
        )
    except Exception as exc:
        log.debug("Failed to persist answer mode preference: %s", exc)


def _get_session_mode(session_id: str) -> Optional[str]:
    try:
        session_repo = get_sqlite_manager().get_session_repository()
        session = session_repo.get_or_create_session(session_id, int(time.time()))
        return session.preferred_answer_style
    except Exception as exc:
        log.debug("Failed to read answer mode preference: %s", exc)
        return None
