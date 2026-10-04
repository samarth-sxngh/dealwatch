"""Vertical plugin registry for multi-vertical comparison architecture."""

import logging

from app.verticals.base import VerticalPlugin

logger = logging.getLogger(__name__)


class VerticalRegistry:
    """Registry maintaining available vertical plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, VerticalPlugin] = {}

    def register(self, plugin: VerticalPlugin) -> None:
        if plugin.name in self._plugins:
            logger.warning("Overwriting vertical plugin: %s", plugin.name)
        self._plugins[plugin.name] = plugin
        logger.info("Registered vertical plugin: %s", plugin.name)

    def get(self, name: str) -> VerticalPlugin:
        plugin = self._plugins.get(name)
        if not plugin:
            raise ValueError(
                f"Vertical '{name}' is not registered or supported. "
                f"Available verticals: {list(self._plugins.keys())}"
            )
        return plugin

    def list_verticals(self) -> list[str]:
        return list(self._plugins.keys())


registry = VerticalRegistry()
