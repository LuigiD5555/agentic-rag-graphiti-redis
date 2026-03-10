"""
OllamaModelProvisioner — ensures required models are available locally.

Pulls any missing model via OllamaModelManager.ensure_model().

CLI usage:
    python -m src.backends.llm.ollama.model_provisioner
    python -m src.backends.llm.ollama.model_provisioner --models llama3.2 nomic-embed-text
    python -m src.backends.llm.ollama.model_provisioner --base-url http://localhost:11434

Programmatic:
    from src.backends.llm.ollama.model_provisioner import OllamaModelProvisioner
    OllamaModelProvisioner().provision_all()
"""
from __future__ import annotations

import logging
import sys
from typing import Dict, Optional

from src.backends.llm.ollama.model_manager import OllamaModelManager

logger = logging.getLogger(__name__)

# Default models needed for the SWARM RAG system.
# Specialist models (code, math) are commented out — large downloads, opt-in only.
DEFAULT_MODELS: Dict[str, str] = {
    "chat": "llama3.2",           # ~2 GB — general chat + RAG verbalization
    "embed": "nomic-embed-text",  # ~274 MB — 768-dim, matches EMBEDDING_DIM default
    # "code":  "deepseek-coder-v2:16b",  # ~9 GB — code understanding / generation
    # "math":  "qwen2.5-math:7b",        # ~4 GB — math reasoning
}


class OllamaModelProvisioner:
    """
    Ensures a set of Ollama models are available locally, pulling any that are missing.

    Args:
        base_url:     Ollama server URL (default: http://localhost:11434)
        models:       role -> model_name dict (default: DEFAULT_MODELS)
        require_live: Propagated to OllamaModelManager — raises on server failure if True
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        models: Optional[Dict[str, str]] = None,
        require_live: bool = False,
    ) -> None:
        self._manager = OllamaModelManager(base_url, require_live=require_live)
        self._models = models if models is not None else DEFAULT_MODELS

    def provision_all(self) -> Dict[str, bool]:
        """Ensure all configured models are present. Returns {role: success}."""
        results: Dict[str, bool] = {}
        for role, name in self._models.items():
            logger.info("Provisioning model for role '%s': %s", role, name)
            ok = self._manager.ensure_model(name)
            results[role] = ok
            if not ok:
                logger.warning("Could not provision '%s' for role '%s'", name, role)
        return results

    def provision_one(self, model_name: str) -> bool:
        """Ensure a single model is present."""
        return self._manager.ensure_model(model_name)


def _cli_main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Ensure Ollama models are pulled locally for SWARM RAG."
    )
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument(
        "--models", nargs="*",
        help="Specific model name(s) to pull. Default: all configured models."
    )
    args = parser.parse_args()

    provisioner = OllamaModelProvisioner(base_url=args.base_url)

    if args.models:
        results = {m: provisioner.provision_one(m) for m in args.models}
    else:
        results = provisioner.provision_all()

    failed = [k for k, ok in results.items() if not ok]
    if failed:
        print(f"FAILED to provision: {failed}", file=sys.stderr)
        sys.exit(1)

    print(f"All models provisioned: {list(results.keys())}")


if __name__ == "__main__":
    _cli_main()
