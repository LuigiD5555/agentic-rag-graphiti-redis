from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AppConfig:
    """
    Minimal Django-like AppConfig.

    External packages can provide an AppConfig and register themselves via
    the app registry loading mechanism (Config.INSTALLED_APPS or entry points).
    """

    name: str
    label: str

    def ready(self) -> None:
        """
        Hook executed after the app registry is populated.

        Apps should perform registrations here (e.g. register providers).
        """

        return
