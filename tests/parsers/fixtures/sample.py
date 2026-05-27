"""Sample Python module for parser testing."""

import os
from pathlib import Path


class DataProcessor:
    """Processes data records."""

    def __init__(self, config: dict) -> None:
        self.config = config

    def process(self, data: list[str]) -> list[str]:
        """Process a list of data strings."""
        return [self._transform(item) for item in data]

    def _transform(self, item: str) -> str:
        result = item.strip().lower()
        return result


def load_data(filepath: str) -> list[str]:
    """Load data from a file."""
    path = Path(filepath)
    return path.read_text().splitlines()
