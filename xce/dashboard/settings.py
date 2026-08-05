"""
Settings Manager for XCE Dashboard
Manages dashboard configuration
"""

import json
import os
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Any, List


@dataclass
class DashboardSettings:
    """Dashboard settings"""
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "xce_dev_password"
    embedding_model: str = "amazon.titan-embed-text-v1"
    embedding_dimensions: int = 1536
    batch_size: int = 100
    server_port: int = 8080
    auth_enabled: bool = False
    auth_username: str = "admin"
    auth_password: str = ""


class SettingsManager:
    """Manages dashboard settings"""
    
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._defaults = DashboardSettings()
    
    def load(self) -> DashboardSettings:
        """Load settings from file"""
        if not self.config_path.exists():
            return self._defaults
        
        try:
            with open(self.config_path) as f:
                data = json.load(f)
            
            # Merge with defaults
            settings = self._defaults
            for key, value in data.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
            return settings
        except:
            return self._defaults
    
    def save(self, settings: Dict[str, Any]):
        """Save settings to file"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing to preserve password if not provided
        existing = self.load()
        for key, value in settings.items():
            if value is not None and hasattr(existing, key):
                setattr(existing, key, value)
        
        with open(self.config_path, "w") as f:
            json.dump(asdict(existing), f, indent=2)
    
    def validate(self, settings: Dict[str, Any]) -> List[str]:
        """Validate settings"""
        errors = []
        
        # Validate Neo4j URI
        if "neo4j_uri" in settings:
            uri = settings["neo4j_uri"]
            if not uri.startswith("bolt://") and not uri.startswith("neo4j://"):
                errors.append("neo4j_uri must start with bolt:// or neo4j://")
        
        # Validate port
        if "server_port" in settings:
            port = settings["server_port"]
            if not isinstance(port, int) or port < 1 or port > 65535:
                errors.append("server_port must be between 1 and 65535")
        
        # Validate embedding dimensions
        if "embedding_dimensions" in settings:
            dims = settings["embedding_dimensions"]
            if dims not in [256, 512, 768, 1024, 1536, 2048]:
                errors.append("embedding_dimensions should be a standard value (256, 512, 768, 1024, 1536, 2048)")
        
        # Validate batch size
        if "batch_size" in settings:
            batch = settings["batch_size"]
            if not isinstance(batch, int) or batch < 1 or batch > 1000:
                errors.append("batch_size must be between 1 and 1000")
        
        return errors
    
    def reset_to_defaults(self):
        """Reset settings to defaults"""
        with open(self.config_path, "w") as f:
            json.dump(asdict(self._defaults), f, indent=2)