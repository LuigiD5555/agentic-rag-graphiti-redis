"""WebSearch app configuration."""


class WebSearchAppConfig:
    """Configuration for web search integration (SearXNG)."""

    name = "src.apps.websearch"
    verbose_name = "Web Search Integration"

    def ready(self):
        """Called when the app is loaded."""
        # Future: register web search providers, hooks, etc.
        pass
