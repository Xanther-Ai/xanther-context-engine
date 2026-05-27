# SWE-Bench Verified: Competitive Comparison Test

## Objective

Run real SWE-bench Verified issues against Django using three context engines:
1. **Xanther (XCE)** — PRAT-based hierarchical graph
2. **Augment Code** — Auggie context engine
3. **Serena** — LSP-based semantic retrieval

Measure which tool helps an AI agent resolve real bugs faster and more accurately.

---

## Setup

### Prerequisites

```bash
# 1. Clone Django
git clone https://github.com/django/django.git ~/Documents/Projects/django

# 2. XCE is already indexed (community--django, 14.5k nodes)
# Verify: curl https://mcp.xanther.ai/health

# 3. Augment is installed and authenticated
auggie login  # Already done

# 4. Serena (install via uvx)
uvx serena --help
# Or: pip install serena
```

### MCP Server Configuration

All three tools configured in `.kiro/settings/mcp.json`:

```json
{
  "mcpServers": {
    "xanther-xce": {
      "url": "https://mcp.xanther.ai/sse",
      "headers": { "Authorization": "Bearer xce_test_django_key_2026" }
    },
    "augment-context-engine": {
      "command": "auggie",
      "args": ["--mcp", "--mcp-auto-workspace"]
    },
    "serena": {
      "command": "uvx",
      "args": ["serena", "--workspace", "~/Documents/Projects/django"]
    }
  }
}
```

---

## Test Issues (SWE-bench Verified — Django)

### Issue Set (10 real bugs from SWE-bench Verified)

| # | Issue ID | Title | Difficulty |
|---|----------|-------|------------|
| 1 | django__django-16379 | `FileBasedCache` has_key is susceptible to race conditions | Medium |
| 2 | django__django-16527 | `AdminSite.catch_all_view` doesn't respect `APPEND_SLASH` | Medium |
| 3 | django__django-16595 | Migration optimizer does not reduce multiple `AlterField` | Hard |
| 4 | django__django-16816 | `makemigrations --check` does not return proper exit code | Easy |
| 5 | django__django-16873 | Template filter `join` should not escape the joining string | Medium |
| 6 | django__django-16910 | `QuerySet.only()` after `select_related()` crash | Hard |
| 7 | django__django-17051 | `bulk_create` with `update_conflicts` should return IDs | Medium |
| 8 | django__django-17087 | Class decorators don't work with `method_decorator` | Medium |
| 9 | django__django-16255 | Signer uses SHA-256 but docs say SHA-1 | Easy |
| 10 | django__django-16400 | `migrate --run-syncdb` crashes on custom user model | Hard |

---

## Test Protocol

### For Each Issue:

1. **Present the bug report** to the agent (same prompt for all three tools)
2. **Allow the agent to use ONE context tool** to understand the codebase
3. **Measure:**
   - Time to locate the correct file/function
   - Number of tool calls needed
   - Token usage (context retrieved)
   - Whether the agent produces a correct fix
   - Whether the fix breaks other tests

### Prompt Template

```
You are fixing a bug in Django. Here is the issue:

[ISSUE TITLE]
[ISSUE DESCRIPTION]

Use the available context tools to understand the relevant code,
then produce a patch that fixes the issue.

Do NOT modify test files. Only fix the source code.
```

---

## Scoring Rubric

| Metric | Weight | Description |
|--------|--------|-------------|
| **Correct Fix** | 40% | Does the patch resolve the issue? |
| **No Regressions** | 20% | Does the existing test suite still pass? |
| **Context Efficiency** | 15% | How many tokens of context were retrieved? |
| **Speed** | 15% | How many tool calls to find the right code? |
| **Completeness** | 10% | Does the fix handle edge cases? |

### Scoring Scale

- **3 points** — Correct fix, no regressions, efficient context
- **2 points** — Correct fix but inefficient (too much context, many calls)
- **1 point** — Partial fix or fix with regressions
- **0 points** — Wrong fix or unable to locate the issue

---

## Expected Results (Hypothesis)

| Tool | Predicted Score (out of 30) | Why |
|------|----------------------------|-----|
| **XCE** | 24-27 | Architecture context helps locate code fast, impact analysis prevents regressions |
| **Augment** | 18-22 | Good embedding search but no architecture awareness |
| **Serena** | 16-20 | Symbol-level search works but no module-level understanding |

### Where XCE Should Win

1. **Issues requiring cross-module understanding** (16595, 16910, 16400)
   - XCE knows module boundaries and dependencies
   - Others will dump too many files

2. **Issues requiring impact analysis** (16527, 17051)
   - XCE can trace what depends on the changed code
   - Others can't predict regressions

3. **Issues in deeply nested code** (16379, 16873)
   - XCE's HLD→LLD→function hierarchy finds the right level fast
   - Others search linearly

### Where Others Might Tie or Win

1. **Simple single-file bugs** (16816, 16255)
   - All tools can find a single file quickly
   - Serena's LSP might be slightly faster for symbol lookup

---

## Running the Test

### Step 1: Prepare Django at the correct commit

Each SWE-bench issue has a base commit. Checkout that commit before testing:

```bash
cd ~/Documents/Projects/django
git checkout <base_commit_sha>
```

### Step 2: Run with XCE

```bash
# Use Kiro with only xanther-xce MCP enabled
# Disable augment and serena temporarily
# Present the issue prompt
# Record: tool calls, tokens, time, result
```

### Step 3: Run with Augment

```bash
# Use Kiro with only augment-context-engine MCP enabled
# Same issue prompt
# Record same metrics
```

### Step 4: Run with Serena

```bash
# Use Kiro with only serena MCP enabled
# Same issue prompt
# Record same metrics
```

### Step 5: Verify fixes

```bash
cd ~/Documents/Projects/django
# Apply each patch
git apply patch_xce.diff
python -m pytest tests/ -x --timeout=60
# Record pass/fail
```

---

## Output Format

For each issue, produce a comparison table:

```markdown
### Issue: django__django-16379

| Metric | XCE | Augment | Serena |
|--------|-----|---------|--------|
| Tool calls | 2 | 5 | 4 |
| Tokens retrieved | 1,200 | 4,500 | 3,200 |
| Time to locate | 8s | 22s | 18s |
| Correct fix | ✅ | ✅ | ❌ |
| Tests pass | ✅ | ⚠️ (1 fail) | N/A |
| Score | 3 | 2 | 0 |
```

---

## Final Deliverable

A published comparison report showing:
1. Aggregate scores across all 10 issues
2. Per-issue breakdown
3. Token efficiency comparison (bar chart)
4. Time-to-fix comparison
5. Qualitative analysis of where each tool excels/fails

This becomes content for:
- Blog post on xanther.ai
- Competitive demo page
- Investor/YC pitch deck data

---

## Notes

- Run each test 3 times to account for LLM variance
- Use the same model (Sonnet 4.0) for all runs
- Record full conversation logs for analysis
- Git stash between runs to ensure clean state