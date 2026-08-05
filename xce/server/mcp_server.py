"""MCP Server for the Xanther Context Engine.

Exposes XCE tools via the Model Context Protocol.
Supports stdio (local) and SSE (remote via FastAPI) transport.

Run locally:  python -m xce.mcp_server
Run remote:   python -m xce.mcp_server --sse
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

# Import XME tools and merge into the tool list
try:
    from xme.server.mcp_tools import XME_TOOLS, XMEToolHandler, is_xme_tool
    _XME_AVAILABLE = True
except ImportError:
    XME_TOOLS = []
    _XME_AVAILABLE = False

    def is_xme_tool(name: str) -> bool:
        return False

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

# Merge XME tools if available
TOOLS: list[Tool] = [
    Tool(
        name="xce_architecture_context",
        description="Get architectural context for a file or symbol",
        inputSchema={
            "type": "object",
            "properties": {
                "file_or_symbol": {"type": "string", "description": "File path or symbol name"},
                "repo_id": {"type": "string", "description": "Repository identifier"},
            },
            "required": ["file_or_symbol", "repo_id"],
        },
    ),
    Tool(
        name="xce_trace",
        description="Trace relationships between code and design artifacts",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source code symbol or file"},
                "target_level": {
                    "type": "string",
                    "enum": ["code", "component", "architecture"],
                    "description": "Target abstraction level",
                },
                "repo_id": {"type": "string", "description": "Repository identifier"},
            },
            "required": ["source", "target_level", "repo_id"],
        },
    ),
    Tool(
        name="xce_impact_analysis",
        description="Predict blast radius for proposed code changes",
        inputSchema={
            "type": "object",
            "properties": {
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of changed file paths",
                },
                "repo_id": {"type": "string", "description": "Repository identifier"},
            },
            "required": ["changed_files", "repo_id"],
        },
    ),
    Tool(
        name="xce_search",
        description="Search the knowledge graph by semantic meaning or symbol",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "repo_id": {"type": "string", "description": "Repository identifier"},
                "search_type": {
                    "type": "string",
                    "enum": ["semantic", "symbol", "tag"],
                    "description": "Type of search to perform",
                },
            },
            "required": ["query", "repo_id"],
        },
    ),
    Tool(
        name="xce_index_repo",
        description="Index or re-index a code repository",
        inputSchema={
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to the repository"},
                "repo_id": {"type": "string", "description": "Repository identifier"},
                "incremental": {
                    "type": "boolean",
                    "default": True,
                    "description": "Only re-index changed files",
                },
            },
            "required": ["repo_path", "repo_id"],
        },
    ),
]

# Append XME tools to the unified TOOLS list
if _XME_AVAILABLE:
    TOOLS.extend(XME_TOOLS)

# Map tool name → required fields for validation
_REQUIRED_FIELDS: dict[str, list[str]] = {
    t.name: t.inputSchema.get("required", []) for t in TOOLS  # type: ignore[union-attr]
}

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    t.name: t.inputSchema for t in TOOLS  # type: ignore[misc]
}

_PROPERTY_TYPES: dict[str, dict[str, str]] = {}
for _t in TOOLS:
    schema = _t.inputSchema  # type: ignore[union-attr]
    props = schema.get("properties", {})
    _PROPERTY_TYPES[_t.name] = {k: v.get("type", "string") for k, v in props.items()}


# ---------------------------------------------------------------------------
# 9.3  Input validation
# ---------------------------------------------------------------------------


class ValidationError(Exception):
    """Raised when tool arguments fail validation."""


def validate_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    """Validate arguments against the tool's JSON schema.

    Raises ``ValidationError`` on missing required fields or wrong types.
    """
    if tool_name not in _REQUIRED_FIELDS:
        raise ValidationError(f"Unknown tool: {tool_name}")

    # Check required fields
    for field in _REQUIRED_FIELDS[tool_name]:
        if field not in arguments:
            raise ValidationError(f"Missing required argument: {field}")

    # Check types
    prop_types = _PROPERTY_TYPES.get(tool_name, {})
    for key, value in arguments.items():
        if key not in prop_types:
            continue  # extra fields are allowed
        expected = prop_types[key]
        if expected == "string" and not isinstance(value, str):
            raise ValidationError(f"Argument '{key}' must be a string, got {type(value).__name__}")
        elif expected == "array" and not isinstance(value, list):
            raise ValidationError(f"Argument '{key}' must be an array, got {type(value).__name__}")
        elif expected == "boolean" and not isinstance(value, bool):
            raise ValidationError(f"Argument '{key}' must be a boolean, got {type(value).__name__}")


# ---------------------------------------------------------------------------
# 9.1 / 9.2  XCEMCPServer
# ---------------------------------------------------------------------------


class XCEMCPServer:
    """MCP server that registers 5 tools and routes calls to agents."""

    def __init__(
        self,
        agents: dict[str, Any] | None = None,
        summarizer: Any | None = None,
        indexer: Any | None = None,
        *,
        auto_journal: bool = True,
    ) -> None:
        self.server = Server("xanther-context-engine")
        self._agents = agents or {}
        self._summarizer = summarizer
        self._indexer = indexer
        self._auto_journal = auto_journal
        self._middleware: Any = None  # JournalingMiddleware, lazy-init
        self._register_handlers()

    # -- tool registration -------------------------------------------

    def get_tools(self) -> list[Tool]:
        return list(TOOLS)

    def _register_handlers(self) -> None:
        @self.server.list_tools()
        async def _list_tools() -> list[Tool]:
            return self.get_tools()

        @self.server.call_tool()
        async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
            # If auto-journaling is on and middleware is ready, route through it
            if self._auto_journal and self._middleware is not None:
                return await self._middleware.handle(name, arguments)
            return await self.handle_tool_call(name, arguments)

    def _get_middleware(self) -> Any:
        """Lazy-init the journaling middleware."""
        if self._middleware is None and self._auto_journal:
            from xce.memory.lifecycle import JournalingMiddleware
            self._middleware = JournalingMiddleware(self)
        return self._middleware
    # -- 9.2  routing ------------------------------------------------

    async def handle_tool_call(
        self, name: str, arguments: dict[str, Any],
    ) -> list[TextContent]:
        """Route MCP tool calls to the appropriate agent."""
        # Validate
        try:
            validate_tool_arguments(name, arguments)
        except ValidationError as exc:
            return [TextContent(type="text", text=json.dumps({
                "error": str(exc),
                "tool": name,
            }))]

        try:
            result = await self._dispatch(name, arguments)
            return [TextContent(type="text", text=json.dumps(result))]
        except Exception as exc:
            logger.exception("Tool call %s failed", name)
            return [TextContent(type="text", text=json.dumps({
                "error": f"Internal error: {exc}",
                "tool": name,
            }))]

    async def _dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "xce_architecture_context":
            agent = self._agents.get("architecture")
            if not agent:
                return {"error": "Architecture agent not configured"}
            result = await agent.query(args["file_or_symbol"], args["repo_id"])
            return self._format_result(result)

        elif name == "xce_trace":
            agent = self._agents.get("traceability")
            if not agent:
                return {"error": "Traceability agent not configured"}
            result = await agent.trace(args["source"], args["target_level"], args["repo_id"])
            return self._format_result(result)

        elif name == "xce_impact_analysis":
            agent = self._agents.get("impact")
            if not agent:
                return {"error": "Impact analysis agent not configured"}
            result = await agent.analyze(args["changed_files"], args["repo_id"])
            return self._format_result(result)

        elif name == "xce_search":
            agent = self._agents.get("search")
            if not agent:
                return {"error": "Search agent not configured"}
            result = await agent.search(
                args["query"], args["repo_id"],
                search_type=args.get("search_type", "semantic"),
            )
            return self._format_result(result)

        elif name == "xce_index_repo":
            if not self._indexer:
                return {"error": "Indexer not configured"}
            result = await self._indexer.index_repository(
                args["repo_path"], args["repo_id"],
                incremental=args.get("incremental", True),
            )
            return {"status": "ok", "result": str(result)}

        # Route to XME tool handler (new generic memory engine)
        if _XME_AVAILABLE and is_xme_tool(name):
            if not hasattr(self, "_xme_handler"):
                self._xme_handler = XMEToolHandler()
            return await self._xme_handler.dispatch(name, args)

        return {"error": f"Unknown tool: {name}"}

    @staticmethod
    def _format_result(result: Any) -> dict[str, Any]:
        """Convert a TraversalResult to a JSON-serializable dict."""
        return {
            "contexts": result.contexts,
            "reasoning": result.reasoning,
            "confidence": result.confidence,
            "nodes_visited": result.nodes_visited,
        }

    # ---------------------------------------------------------------
    # XME helpers
    # ---------------------------------------------------------------

    @staticmethod
    def _open_memory_store(repo_path: str) -> Any:
        from xce.memory.store import MemoryStore
        return MemoryStore.open(repo_path)

    async def _xme_remember(self, args: dict[str, Any]) -> dict[str, Any]:
        from xce.memory.models import (
            DecisionNode, AttemptNode, SessionNode,
            UserPreferenceNode, TeamConventionNode,
        )
        import asyncio

        repo_path = args["repo_path"]
        node_type = args["node_type"]
        data = args.get("data", {})

        def _write() -> dict[str, Any]:
            with self._open_memory_store(repo_path) as store:
                if node_type == "decision":
                    node = DecisionNode.from_dict(data)
                    store.save_decision(node)
                    return {"status": "ok", "node_type": "decision", "id": node.id}
                elif node_type == "attempt":
                    node = AttemptNode.from_dict(data)
                    store.save_attempt(node)
                    return {"status": "ok", "node_type": "attempt", "id": node.id}
                elif node_type == "session":
                    node = SessionNode.from_dict(data)
                    store.save_session(node)
                    return {"status": "ok", "node_type": "session", "id": node.id}
                elif node_type == "preference":
                    node = UserPreferenceNode.from_dict(data)
                    store.save_preference(node)
                    return {"status": "ok", "node_type": "preference", "id": node.id}
                elif node_type == "convention":
                    node = TeamConventionNode.from_dict(data)
                    store.save_convention(node)
                    return {"status": "ok", "node_type": "convention", "id": node.id}
                else:
                    return {"error": f"Unknown node_type: {node_type}"}

        return await asyncio.get_event_loop().run_in_executor(None, _write)

    async def _xme_history(self, args: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        repo_path = args["repo_path"]
        file_or_symbol = args["file_or_symbol"]
        limit = int(args.get("limit", 10))

        def _read() -> dict[str, Any]:
            with self._open_memory_store(repo_path) as store:
                # Search sessions and attempts that mention this file/symbol
                results = store.search(
                    file_or_symbol,
                    scope=None,
                    limit=limit,
                )
                return {
                    "file_or_symbol": file_or_symbol,
                    "history": [
                        {
                            "node_type": r.node_type,
                            "id": r.node_id,
                            "scope": r.scope.value,
                            "summary": r.summary,
                            "score": round(r.score, 3),
                        }
                        for r in results
                    ],
                    "count": len(results),
                }

        return await asyncio.get_event_loop().run_in_executor(None, _read)

    async def _xme_decisions(self, args: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        repo_path = args["repo_path"]
        module_or_component = args.get("module_or_component", "")
        include_reverted = bool(args.get("include_reverted", False))
        limit = int(args.get("limit", 20))

        def _read() -> dict[str, Any]:
            with self._open_memory_store(repo_path) as store:
                if module_or_component:
                    decisions = store.list_decisions_for_module(module_or_component)
                else:
                    decisions = store.list_decisions(
                        limit=limit, include_reverted=include_reverted
                    )
                return {
                    "query": module_or_component,
                    "decisions": [d.to_dict() for d in decisions[:limit]],
                    "count": len(decisions[:limit]),
                }

        return await asyncio.get_event_loop().run_in_executor(None, _read)

    async def _xme_attempts(self, args: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        repo_path = args["repo_path"]
        problem_query = args["problem_query"]
        result_filter = args.get("result_filter") or None
        limit = int(args.get("limit", 10))

        def _read() -> dict[str, Any]:
            with self._open_memory_store(repo_path) as store:
                # Keyword search over attempts
                from xce.memory.models import MemoryScope
                results = store.search(
                    problem_query,
                    scope=MemoryScope.TEAM,
                    limit=limit * 3,  # over-fetch then filter
                )
                attempts = [
                    r for r in results if r.node_type == "attempt"
                    and (result_filter is None or r.data.get("result") == result_filter)
                ][:limit]
                return {
                    "query": problem_query,
                    "attempts": [r.data for r in attempts],
                    "count": len(attempts),
                }

        return await asyncio.get_event_loop().run_in_executor(None, _read)

    async def _xme_sync(self, args: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        repo_path = args["repo_path"]
        direction = args.get("direction", "sync")

        def _do_sync() -> dict[str, Any]:
            from xce.memory.sync import MemorySyncer
            with self._open_memory_store(repo_path) as store:
                syncer = MemorySyncer(
                    memory_dir=store._dir,
                    repo_root=repo_path,
                )
                if direction == "push":
                    result = syncer.push(store)
                    return {"direction": "push", "pushed": result}
                elif direction == "pull":
                    result = syncer.pull(store)
                    return {"direction": "pull", "pulled": result}
                else:
                    result = syncer.sync(store)
                    return {"direction": "sync", **result}

        return await asyncio.get_event_loop().run_in_executor(None, _do_sync)

    async def _xme_journal_append(self, args: dict[str, Any]) -> dict[str, Any]:
        from xce.memory.journal import ChatJournal
        import asyncio

        repo_path = args["repo_path"]
        role = args["role"]
        content = args["content"]
        tool_name = args.get("tool_name", "")
        session_id = args.get("session_id", "")

        def _write() -> dict[str, Any]:
            memory_dir = str(self._open_memory_store(repo_path)._dir)
            journal = ChatJournal(
                memory_dir=memory_dir,
                session_id=session_id,
            )
            if role == "tool":
                journal.append_tool_call(
                    tool_name=tool_name or "unknown",
                    args={},
                    result_summary=content,
                )
            elif role == "note":
                journal.note(content)
            else:
                journal.append_turn(role=role, content=content)
            journal.flush_sync()
            return {"status": "ok", "role": role, "date": journal._date_str}

        return await asyncio.get_event_loop().run_in_executor(None, _write)

    async def _xme_journal_compact(self, args: dict[str, Any]) -> dict[str, Any]:
        from xce.memory.journal import ChatJournal, COMPACTION_THRESHOLD_LINES
        import asyncio

        repo_path = args["repo_path"]
        force = bool(args.get("force", False))

        async def _do_compact() -> dict[str, Any]:
            with self._open_memory_store(repo_path) as store:
                memory_dir = str(store._dir)
                journal = ChatJournal(memory_dir=memory_dir)

                log_text = journal.read_daily_log()
                line_count = log_text.count("\n")

                if not force and line_count < COMPACTION_THRESHOLD_LINES:
                    return {
                        "status": "skipped",
                        "reason": f"log has {line_count} lines, threshold={COMPACTION_THRESHOLD_LINES}",
                        "lines": line_count,
                    }

                result = await journal.compact(store)
                return {
                    "status": "compacted",
                    "lines_before": result.lines_before,
                    "lines_after": result.lines_after,
                    "reduction_pct": result.reduction_pct,
                    "promoted": result.promoted,
                }

        return await _do_compact()

    async def _xme_get_context(self, args: dict[str, Any]) -> dict[str, Any]:
        """Return the full memory context snapshot for prompt injection."""
        import asyncio
        repo_path = args["repo_path"]

        async def _build() -> dict[str, Any]:
            from xce.memory.lifecycle import SessionContext
            # Use a lightweight context (don't start a full session)
            with self._open_memory_store(repo_path) as store:
                from xce.memory.journal import ChatJournal
                from xce.memory.lifecycle import _format_context_block, _DEFAULT_XME_DIR
                from pathlib import Path
                memory_dir = store._dir
                journal = ChatJournal(memory_dir=str(memory_dir))
                repo_id = Path(repo_path).name

                decisions = store.list_decisions(repo_id=repo_id, limit=5)
                failures = store.list_attempts(repo_id=repo_id, result_filter="failed", limit=3)
                prefs = store.get_preferences(repo_id=repo_id)
                recent_log = journal.read_daily_log()
                log_lines = recent_log.splitlines()
                recent_log_short = "\n".join(log_lines[-40:])

                context_block = _format_context_block(
                    repo_id=repo_id,
                    top_decisions=[{"title": d.title, "decision": d.decision, "outcome": d.outcome} for d in decisions],
                    top_failures=[{"problem": a.problem[:120], "failure_reason": a.failure_reason[:120], "lessons_learned": a.lessons_learned[:120]} for a in failures],
                    preferences=[{"key": p.key, "value": p.value} for p in prefs],
                    recent_log=recent_log_short,
                )
                return {
                    "repo_id": repo_id,
                    "context_block": context_block,
                    "decisions_count": len(decisions),
                    "failures_count": len(failures),
                    "preferences_count": len(prefs),
                    "has_recent_log": bool(recent_log.strip()),
                }

        return await _build()

    async def _xme_session_end(self, args: dict[str, Any]) -> dict[str, Any]:
        """End the current session: flush, compact, save SessionNode."""
        from xce.memory.lifecycle import SessionContext
        import asyncio

        repo_path = args["repo_path"]
        summary = args.get("summary", "")
        outcome = args.get("outcome", "unknown")
        files_touched = args.get("files_touched", [])
        problem_statement = args.get("problem_statement", "")

        # If middleware has an active session, end it properly
        middleware = self._get_middleware()
        if middleware and repo_path in middleware._sessions:
            await middleware.end_session(
                repo_path,
                summary=summary,
                outcome=outcome,
                files_touched=files_touched,
            )
            return {
                "status": "session_ended",
                "repo_path": repo_path,
                "outcome": outcome,
                "via": "middleware",
            }

        # No active session — do a standalone end
        async def _standalone_end() -> dict[str, Any]:
            ctx = await SessionContext.start(repo_path=repo_path)
            await ctx.end(
                summary=summary,
                outcome=outcome,
                files_touched=files_touched,
                problem_statement=problem_statement,
            )
            return {
                "status": "session_ended",
                "session_id": ctx.session_id,
                "repo_path": repo_path,
                "outcome": outcome,
                "via": "standalone",
            }

        return await _standalone_end()

    # -- 9.4  transport ----------------------------------------------

    async def run_stdio(self) -> None:
        """Run the MCP server over stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream, write_stream,
                self.server.create_initialization_options(),
            )

    def create_sse_app(self) -> Any:
        """Create a FastAPI app with SSE transport for remote deployment."""
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse

        app = FastAPI(title="XCE MCP Server")

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok"}

        @app.get("/tools")
        async def list_tools() -> list[dict[str, Any]]:
            return [
                {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                for t in self.get_tools()
            ]

        @app.post("/call")
        async def call_tool(request: Request) -> JSONResponse:
            body = await request.json()
            name = body.get("name", "")
            arguments = body.get("arguments", {})
            results = await self.handle_tool_call(name, arguments)
            return JSONResponse(content={
                "content": [{"type": r.type, "text": r.text} for r in results],
            })

        return app


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    server = XCEMCPServer()
    if "--sse" in sys.argv:
        import uvicorn
        app = server.create_sse_app()
        config = uvicorn.Config(app, host="0.0.0.0", port=8000)
        srv = uvicorn.Server(config)
        await srv.serve()
    else:
        await server.run_stdio()


if __name__ == "__main__":
    asyncio.run(main())
