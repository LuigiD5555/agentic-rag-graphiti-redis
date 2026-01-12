"""
API endpoints for managing ingestion exclusion paths.

These endpoints allow the UI to update .ingestignore without editing files manually.
"""

from pathlib import Path
from typing import List, Dict

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.conf import settings as app_settings


router = APIRouter(prefix="/exclusions", tags=["exclusions"])


class ExclusionsConfig(BaseModel):
    """List of exclusion patterns/paths used during ingestion."""

    excludes: List[str] = Field(default_factory=list)
    path: str | None = None


def _get_ingestignore_path() -> Path:
    return app_settings.BASE_DIR / ".ingestignore"


def _read_exclusions(file_path: Path) -> List[str]:
    if not file_path.exists():
        return []

    excludes: List[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        excludes.append(stripped)
    return excludes


def _write_exclusions(file_path: Path, excludes: List[str]) -> None:
    header_lines: List[str] = []
    if file_path.exists():
        for line in file_path.read_text(encoding="utf-8").splitlines():
            if line.strip() == "" or line.lstrip().startswith("#"):
                header_lines.append(line)
            else:
                break
    else:
        header_lines = [
            "# Patterns, relative paths, or absolute paths to exclude from ingestion.",
            "#",
            "# Examples:",
            "#   node_modules/",
            "#   **/__pycache__/**",
            "#   data/private/**",
            "#   /absolute/path/to/secrets.txt",
            "",
        ]

    seen = set()
    normalized: List[str] = []
    for item in excludes:
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    content_lines = header_lines + normalized
    file_path.write_text("\n".join(content_lines).rstrip() + "\n", encoding="utf-8")


@router.get("/", response_model=ExclusionsConfig)
async def get_exclusions() -> ExclusionsConfig:
    """Return the current ingestion exclusions list."""
    ingestignore_path = _get_ingestignore_path()
    excludes = _read_exclusions(ingestignore_path)
    return ExclusionsConfig(excludes=excludes, path=str(ingestignore_path))


@router.post("/", status_code=status.HTTP_200_OK)
async def update_exclusions(config: ExclusionsConfig) -> Dict[str, str | int]:
    """Replace the exclusions list stored in .ingestignore."""
    ingestignore_path = _get_ingestignore_path()
    try:
        _write_exclusions(ingestignore_path, config.excludes)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update exclusions: {exc}",
        ) from exc
    return {
        "success": True,
        "message": f"Updated exclusions ({len(config.excludes)})",
    }
