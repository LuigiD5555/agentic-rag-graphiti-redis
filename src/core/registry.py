"""Registry central para todos los backends del sistema."""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, TypeAlias


BackendCategory: TypeAlias = Literal[
    "llm",
    "embeddings",
    "vector_store",
    "graph_store",
    "cache",
    "reranker",
]


@dataclass
class BackendFactory:
    name: str
    category: BackendCategory
    factory_func: Callable[[Dict[str, Any]], Any]
    description: str = ""


class Registry:
    """Central registry to locate backend factories by category."""

    _backends: Dict[BackendCategory, Dict[str, BackendFactory]] = {
        "llm": {},
        "embeddings": {},
        "vector_store": {},
        "graph_store": {},
        "cache": {},
        "reranker": {},
    }

    @classmethod
    def register(
        cls,
        category: BackendCategory,
        name: str,
        factory: Callable[[Dict[str, Any]], Any],
        description: str = "",
    ) -> None:
        cls._backends[category][name] = BackendFactory(
            name=name,
            category=category,
            factory_func=factory,
            description=description,
        )

    @classmethod
    def get_factory(cls, category: BackendCategory, name: str) -> Callable[[Dict[str, Any]], Any]:
        if name not in cls._backends[category]:
            available = list(cls._backends[category].keys())
            raise KeyError(
                f"Backend '{name}' not registered under category '{category}'. "
                f"Available: {available}"
            )
        return cls._backends[category][name].factory_func

    @classmethod
    def build(cls, category: BackendCategory, config: Dict[str, Any]) -> Any:
        engine = config.get("ENGINE") or config.get("BACKEND")
        if not engine:
            raise KeyError("Config must include 'ENGINE' or 'BACKEND'.")
        factory = cls.get_factory(category, engine)
        return factory(config)

    @classmethod
    def list_backends(cls, category: BackendCategory) -> List[str]:
        return list(cls._backends[category].keys())

    @classmethod
    def is_registered(cls, category: BackendCategory, name: str) -> bool:
        return name in cls._backends[category]

    @classmethod
    def clear(cls, category: BackendCategory | None = None) -> None:
        if category:
            cls._backends[category].clear()
            return
        for cat in cls._backends:
            cls._backends[cat].clear()


# backward compatibility alias
registry = Registry
