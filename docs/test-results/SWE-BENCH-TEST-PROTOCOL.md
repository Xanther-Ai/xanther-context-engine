# SWE-Bench Verified: XCE+XME vs Manual PR Review Protocol

## Objective

Test XCE+XME with cross-session memories against manual PR review on real SWE-bench Verified issues, measuring:
1. Time to fix
2. Token efficiency
3. Correctness of fix
4. Cross-session memory recall

---

## Test Setup

### Repositories
- **Django** - indexed as `django-xme`
- **SymPy** - indexed as `sympy-xme` (new)
- **Pandas** - indexed as `pandas-xme` (new)

### Test Issues (10 SWE-bench Verified — Django)

| # | Issue ID | Difficulty | Description |
|---|----------|------------|-------------|
| 1 | django__django-16379 | Medium | FileBasedCache has_key race condition |
| 2 | django__django-16527 | Medium | AdminSite.catch_all_view ignores APPEND_SLASH |
| 3 | django__django-16595 | Hard | Migration optimizer doesn't reduce multiple AlterField |
| 4 | django__django-16816 | Easy | makemigrations --check exit code wrong |
| 5 | django__django-16873 | Medium | Template filter `join` escapes string |
| 6 | django__django-16910 | Hard | QuerySet.only() after select_related() crash |
| 7 | django__django-17051 | Medium | bulk_create with update_conflicts should return IDs |
| 8 | django__django-17087 | Medium | Class decorators don't work with method_decorator |
| 9 | django__django-16255 | Easy | Signer uses SHA-256 but docs say SHA-1 |
| 10 | django__django-16400 | Hard | migrate --run-syncdb crashes on custom user model |

### Cross-Session Memories to Test

| Memory Type | Description | Use Case |
|-------------|-------------|----------|
| `codebase-patterns` | Architecture-level understanding | Issues 3, 6, 10 |
| `recent-fixes` | Past PR fixes | Issues with similar patterns |
| `api-usage` | How specific APIs work | Issues 5, 7 |
| `test-strategies` | Django testing patterns | All issues |

---

## Test Protocol

### Phase 1: XCE+XME Review (30 seconds)

**Query**: `django <issue_id> <issue_description>`

**XME Cross-Session Recall**:
- Query episodic memory for similar issues
- Retrieve code facts from temporal graph
- Get recent fixes with similar patterns

**Metrics to Record**:
- Time to query (wall clock)
- Tokens in query + retrieved context
- Number of retrieved facts
- Number of related tests found

### Phase 2: Manual Review (2 minutes)

**Actions**:
1. Navigate to Django codebase
2. Search for relevant files (grep/github search)
3. Read relevant files
4. Understand the bug and fix

**Metrics to Record**:
- Time to locate relevant code
- Time to understand the code
- Files read
- Tokens estimated (from reading)

### Phase 3: Agent Attempt

**Using XCE+XME Context**:
- Agent gets retrieved context from XCE+XME
- Agent attempts to produce fix
- Fix is verified with tests

**Without XCE+XME (baseline)**:
- Agent gets raw issue description only
- Agent must search manually or fail
- Fix is verified with tests

---

## Scoring Rubric

### Correctness (40 points)
- ✅ Fix resolves the issue = 20 points
- ✅ No regressions (all tests pass) = 10 points
- ✅ Handles edge cases = 10 points

### Efficiency (30 points)
- Time to locate: <10s = 10 points, <30s = 5 points, >30s = 0 points
- Tokens used: <500 = 10 points, <1000 = 5 points, >1000 = 0 points
- Tool calls: <3 = 10 points, <5 = 5 points, >5 = 0 points

### Cross-Session Memory Effectiveness (30 points)
- Recalls relevant past fixes = 10 points
- Uses architecture knowledge = 10 points
- Uses test strategies = 10 points

**Total**: 100 points per issue

---

## Expected Results (Neutral Hypothesis)

### XCE+XME Should Win On:
1. **Cross-module issues** (16595, 16910, 16400) - Architecture context helps
2. **Impact analysis needs** (16527, 17051) - Can trace dependencies
3. **Deeply nested code** (16379, 16873) - Hierarchical navigation

### Manual Review Might Win On:
1. **Simple single-file bugs** (16816, 16255) - No indexing overhead
2. **Novel problems** - Not in any memory/index
3. **First-time codebase** - No indexing cost yet

---

## Data Collection Template

For each issue, produce:

```markdown
### Issue: django__django-16379

| Metric | XCE+XME | Manual | Manual (baseline) |
|--------|---------|--------|-------------------|
| Time to locate | 12s | 45s | N/A |
| Tokens retrieved | 850 | 1,200 | N/A |
| Tool calls | 2 | 5 | N/A |
| Correct fix | ✅ | ✅ | ❌ |
| Tests pass | ✅ | ✅ | N/A |
| Cross-session recall | ✅ | N/A | N/A |
| Score | 92 | 78 | 45 |
```

---

## Execution Steps

1. **Index repos** (one-time setup)
   ```bash
   xce index ~/Projects/django --mode full
   xce index ~/Projects/sympy --mode full
   xce index ~/Projects/pandas --mode full
   ```

2. **Run test** (per issue)
   ```bash
   # XCE+XME test
   python scripts/run_swebench_test.py --issue django__django-16379 --tool xce-xme
   
   # Manual baseline test
   python scripts/run_swebench_test.py --issue django__django-16379 --tool manual
   ```

3. **Collect results** to `docs/test-results/SWE-BENCH-RESULTS.md`

4. **Generate comparison report** with token spend analysis

---

## Cost Estimation

### Per Issue Cost (XCE+XME)
- Query embedding: ~100 tokens
- Context retrieval: ~300 tokens
- Agent processing: ~500 tokens
- **Total per issue**: ~900 tokens

### Per Issue Cost (Manual)
- Search: ~500 tokens
- Code reading: ~1,200 tokens
- Analysis: ~200 tokens
- **Total per issue**: ~1,900 tokens

### 10 Issues Total
- XCE+XME: 9,000 tokens
- Manual: 19,000 tokens
- **Savings**: 10,000 tokens (53%)
