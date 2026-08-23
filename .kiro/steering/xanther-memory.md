---
inclusion: auto
---

# Xanther Memory System

This project uses Xanther (XCE + XME) for persistent agent memory. Your actions, decisions, and learnings are stored and searchable across sessions.

## After making meaningful changes

At the end of each turn where you made file edits or ran significant commands, silently record what you did:

```bash
python3 .xanther/ingest_turn.py --action "brief description of what you did" --files "file1.py,file2.py"
```

## After making architectural decisions

When you make or document a design decision:

```bash
python3 .xanther/ingest_turn.py --decision "description of the decision and rationale"
```

## After learning something important about this project

When you discover a fact worth remembering:

```bash
python3 .xanther/ingest_turn.py --fact "the important fact to remember"
```

## Before starting complex work

Query memory to check if similar work was done before:

```bash
xanther query "what you're about to do" --repo xanther-context-engine
```

## Rules

- Only record meaningful actions (file edits, commands, not just Q&A)
- Keep summaries to 1 sentence
- Include modified file paths with --files
- Do NOT show the ingest command output to the user
- Run the ingest silently at the end of your turn
