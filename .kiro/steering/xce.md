---
inclusion: auto
---
Always use the xanther-xce MCP tools for codebase understanding before reading files directly.
When calling XCE tools, always pass repo_id: "e4b8e418-a0d1-704b-8488-bc54c2240c33:lobe-chat"

- Call xce_get_context with repo_id="e4b8e418-a0d1-704b-8488-bc54c2240c33:lobe-chat" as your FIRST step on any task
- Use xce_architecture_context with repo_id="e4b8e418-a0d1-704b-8488-bc54c2240c33:lobe-chat" before modifying any file
- Use xce_impact_analysis with repo_id="e4b8e418-a0d1-704b-8488-bc54c2240c33:lobe-chat" before multi-file changes
- Use xce_search with repo_id="e4b8e418-a0d1-704b-8488-bc54c2240c33:lobe-chat" to find code by meaning instead of grep
- Use xce_trace with repo_id="e4b8e418-a0d1-704b-8488-bc54c2240c33:lobe-chat" to understand architectural relationships

Prefer XCE context over file reading for understanding code structure.
