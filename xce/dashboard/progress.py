"""
Progress Tracker for XCE Dashboard
Tracks indexing progress and broadcasts via WebSocket
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class IndexingStatus(str, Enum):
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class IndexingEvent:
    """Indexing event"""
    timestamp: datetime
    level: str  # info, warning, error
    message: str


@dataclass
class IndexingProgress:
    """Indexing progress state"""
    repo_id: str
    total_files: int = 0
    processed_files: int = 0
    current_file: Optional[str] = None
    nodes_created: int = 0
    edges_created: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    estimated_remaining: Optional[float] = None
    status: IndexingStatus = IndexingStatus.STARTED
    events: List[IndexingEvent] = field(default_factory=list)


class ProgressTracker:
    """Tracks and broadcasts indexing progress"""
    
    def __init__(self, websocket_manager):
        self.ws_manager = websocket_manager
        self._progress: Dict[str, IndexingProgress] = {}
        self._start_times: Dict[str, datetime] = {}
    
    async def start_tracking(self, repo_id: str, total_files: int):
        """Start tracking progress for a repository"""
        progress = IndexingProgress(
            repo_id=repo_id,
            total_files=total_files,
            status=IndexingStatus.STARTED
        )
        self._progress[repo_id] = progress
        self._start_times[repo_id] = datetime.now()
        
        await self.ws_manager.broadcast({
            "type": "progress:start",
            "repo_id": repo_id,
            "total_files": total_files
        })
    
    async def update_progress(self, repo_id: str, **kwargs):
        """Update progress metrics"""
        if repo_id not in self._progress:
            return
        
        progress = self._progress[repo_id]
        
        for key, value in kwargs.items():
            if hasattr(progress, key):
                setattr(progress, key, value)
        
        progress.status = IndexingStatus.IN_PROGRESS
        
        # Calculate ETA
        if progress.processed_files > 0 and progress.total_files > 0:
            elapsed = (datetime.now() - self._start_times[repo_id]).total_seconds()
            rate = progress.processed_files / elapsed
            remaining = progress.total_files - progress.processed_files
            progress.estimated_remaining = remaining / rate if rate > 0 else None
        
        # Broadcast update
        await self.ws_manager.broadcast({
            "type": "progress:update",
            "repo_id": repo_id,
            "processed_files": progress.processed_files,
            "current_file": progress.current_file,
            "nodes_created": progress.nodes_created,
            "edges_created": progress.edges_created,
            "estimated_remaining": progress.estimated_remaining,
            "percent": (progress.processed_files / progress.total_files * 100) 
                       if progress.total_files > 0 else 0
        })
    
    async def add_event(self, repo_id: str, level: str, message: str):
        """Add an event to the log"""
        if repo_id not in self._progress:
            return
        
        event = IndexingEvent(
            timestamp=datetime.now(),
            level=level,
            message=message
        )
        self._progress[repo_id].events.append(event)
        
        await self.ws_manager.broadcast({
            "type": "progress:event",
            "repo_id": repo_id,
            "timestamp": event.timestamp.isoformat(),
            "level": level,
            "message": message
        })
    
    async def finish(self, repo_id: str, success: bool, error: Optional[str] = None):
        """Mark indexing as finished"""
        if repo_id not in self._progress:
            return
        
        progress = self._progress[repo_id]
        progress.status = IndexingStatus.COMPLETED if success else IndexingStatus.FAILED
        
        if error:
            progress.events.append(IndexingEvent(
                timestamp=datetime.now(),
                level="error",
                message=error
            ))
        
        # Calculate total time
        elapsed = (datetime.now() - self._start_times[repo_id]).total_seconds()
        
        await self.ws_manager.broadcast({
            "type": "progress:complete",
            "repo_id": repo_id,
            "success": success,
            "error": error,
            "stats": {
                "total_files": progress.total_files,
                "processed_files": progress.processed_files,
                "nodes_created": progress.nodes_created,
                "edges_created": progress.edges_created,
                "elapsed_seconds": elapsed
            }
        })
    
    async def cancel(self, repo_id: str):
        """Cancel ongoing indexing"""
        if repo_id not in self._progress:
            return
        
        self._progress[repo_id].status = IndexingStatus.CANCELLED
        
        await self.ws_manager.broadcast({
            "type": "progress:cancelled",
            "repo_id": repo_id
        })
    
    def get_progress(self, repo_id: str) -> Optional[IndexingProgress]:
        """Get current progress for a repository"""
        return self._progress.get(repo_id)
    
    def get_all_progress(self) -> List[IndexingProgress]:
        """Get all active progress"""
        return list(self._progress.values())