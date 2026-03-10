"""
Plugin manifest schema.

Each plugin ships a manifest.json that declares its capabilities,
inputs/outputs, and dependencies so the Planner can build a correct DAG.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


PluginLevel = Literal["core", "core_plugin", "specialist"]


class PluginManifest(BaseModel):
    name: str
    version: str = "1.0.0"
    capabilities: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    level: PluginLevel = "specialist"
    enabled: bool = True
