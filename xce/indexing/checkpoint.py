"""Indexing checkpoint — resume interrupted indexing from where it stopped.

Saves progress after each batch/node so that if the process is killed,
restarting picks up from the exact same point.

Checkpoint file: .xanther/index_progress_{repo_id}.json
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class IndexCheckpoint:
    """Track and persist indexing progress for resumable indexing.

    Structure:
    {
        "repo_id": "flask",
        "repo_path": "/path/to/flask",
        "layer": "layer2",          # current layer: layer1, graph, layer2, layer3, layer4, embed, bridge
        "completed_layers": ["layer1", "graph"],
        "layer2_done": ["node_id_1", "node_id_2", ...],
        "layer3_done": ["node_id_1", ...],
        "layer4_done": ["module_path_1", ...],
        "embed_done": 1200,         # number of nodes embedded
        "total_nodes": 2895,
    }
    """

    LAYERS = ("layer1", "graph", "layer2", "layer3", "layer4", "embed", "bridge")

    def __init__(self, repo_id: str, checkpoint_dir: str = ".xanther") -> None:
        self._repo_id = repo_id
        self._dir = Path(checkpoint_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"index_progress_{repo_id}.json"
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
                if self._data.get("repo_id") != self._repo_id:
                    self._data = {}
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        self._data["repo_id"] = self._repo_id
        self._path.write_text(json.dumps(self._data, default=str))

    @property
    def has_progress(self) -> bool:
        """True if there's saved progress from a previous run."""
        return bool(self._data.get("completed_layers"))

    @property
    def current_layer(self) -> Optional[str]:
        """The layer that was in progress when interrupted."""
        return self._data.get("layer")

    @property
    def completed_layers(self) -> list[str]:
        return self._data.get("completed_layers", [])

    def is_layer_done(self, layer: str) -> bool:
        return layer in self.completed_layers

    # ------------------------------------------------------------------
    # Mark progress
    # ------------------------------------------------------------------

    def start_layer(self, layer: str) -> None:
        """Mark a layer as in-progress."""
        self._data["layer"] = layer
        self._save()

    def complete_layer(self, layer: str) -> None:
        """Mark a layer as done."""
        done = self._data.setdefault("completed_layers", [])
        if layer not in done:
            done.append(layer)
        self._data["layer"] = None
        self._save()

    def mark_node_done(self, layer: str, node_id: str) -> None:
        """Mark a single node as processed in a layer."""
        key = f"{layer}_done"
        done = self._data.setdefault(key, [])
        done.append(node_id)
        # Save every 10 nodes to reduce I/O
        if len(done) % 10 == 0:
            self._save()

    def flush(self) -> None:
        """Force-save current state."""
        self._save()

    def get_done_nodes(self, layer: str) -> set[str]:
        """Get set of node_ids already processed for a layer."""
        return set(self._data.get(f"{layer}_done", []))

    def set_embed_progress(self, count: int) -> None:
        """Track embedding progress by count."""
        self._data["embed_done"] = count
        if count % 100 == 0:
            self._save()

    def get_embed_progress(self) -> int:
        return self._data.get("embed_done", 0)

    def set_total_nodes(self, count: int) -> None:
        self._data["total_nodes"] = count
        self._save()

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove checkpoint (start fresh)."""
        self._data = {}
        if self._path.exists():
            self._path.unlink()

    def summary(self) -> str:
        """Human-readable summary of checkpoint state."""
        if not self.has_progress:
            return "No previous progress"
        done = self.completed_layers
        current = self.current_layer
        total = self._data.get("total_nodes", "?")
        parts = []
        for layer in self.LAYERS:
            if layer in done:
                parts.append(f"  [green]✓[/green] {layer}")
            elif layer == current:
                n_done = len(self.get_done_nodes(layer)) if layer not in ("embed", "bridge") else self.get_embed_progress()
                parts.append(f"  [yellow]⟳[/yellow] {layer} ({n_done} done)")
            else:
                parts.append(f"  [dim]○[/dim] {layer}")
        return f"Previous run ({total} nodes):\n" + "\n".join(parts)
