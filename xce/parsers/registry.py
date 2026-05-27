"""Parser registry mapping file extensions to parser instances.

The registry is immutable after freeze() is called.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from xce.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class ParserRegistry:
    """Maps file extensions to parser instances. Immutable after freeze()."""

    def __init__(self) -> None:
        self._ext_map: dict[str, BaseParser] = {}
        self._frozen: bool = False

    def register(self, parser: BaseParser) -> None:
        """Register a parser for its supported extensions.

        Raises:
            RuntimeError: If registry is frozen.
            ValueError: If an extension is already registered by another parser.
        """
        if self._frozen:
            raise RuntimeError("Cannot register parsers after registry is frozen")
        for ext in parser.supported_extensions():
            if ext in self._ext_map:
                existing = self._ext_map[ext]
                raise ValueError(
                    f"Extension '{ext}' already registered by "
                    f"{existing.language_name()}, cannot register "
                    f"{parser.language_name()}"
                )
            self._ext_map[ext] = parser

    def freeze(self) -> None:
        """Freeze the registry, preventing further registrations."""
        self._frozen = True

    def get_parser(self, filepath: str) -> Optional[BaseParser]:
        """Return the parser for a file path, or None if unsupported."""
        ext = os.path.splitext(filepath)[1].lower()
        return self._ext_map.get(ext)

    @property
    def supported_extensions(self) -> list[str]:
        """Return all registered extensions."""
        return sorted(self._ext_map.keys())

    @property
    def languages(self) -> list[str]:
        """Return all registered language names (deduplicated)."""
        return sorted(set(p.language_name() for p in self._ext_map.values()))
