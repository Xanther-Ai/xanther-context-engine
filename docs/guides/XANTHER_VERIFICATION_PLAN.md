# Xanther Verification Plan - Quick Test

## Strategy

Rather than re-running the complete 10+ hour comparison test from scratch, we'll:

1. **Index a smaller subset** of Django (core ORM modules only) - ~30 minutes
2. **Test a few representative issues** from the blog post - ~1 hour
3. **Verify XCE performs** per the blog post predictions - ~30 minutes
4. **Create comparison report** - ~30 minutes

Total: ~2.5 hours vs 10+ hours for full replication

## Phase 1: Targeted Django Indexing (30 min)

### Core Modules to Index

These 10 files cover the test cases from the blog post:

```
django/db/models/query.py         # QuerySet (Feature 1, many bugs)
django/db/models/deletion.py      # Deletion logic (Bug analysis)
django/db/models/sql/compiler.py  # SQL compilation (Arch understanding)
django/db/transaction.py          # Transactions (Feature 2)
django/db/models/fields/__init__.py  # Field logic
django/db/cache/backends/base.py  # Caching (Feature 4)
django/db/utils.py                # DB utilities
django/contrib/admin/__init__.py  # Admin (Bug test)
django/db/models/__init__.py      # Model init
django/db/__init__.py             # DB init
```

### Indexing Command

```bash
# Create a minimal indexing job
cd /Users/rajbhattacharya/Documents/Projects/xanther-context-engine
source .venv/bin/activate
export AWS_ACCESS_KEY_ID=""
export AWS_SECRET_ACCESS_KEY=""

# Option A: Full directory (slower but complete)
python3 -m xce index django-repo/django --repo-id django-core --full

# Option B: Direct file indexing if supported
python3 -m xce index-files \
  django-repo/django/db/models/query.py \
  django-repo/django/db/models/deletion.py \
  django-repo/django/db/models/sql/compiler.py \
  django-repo/django/db/transaction.py \
  --repo-id django-core --full
```

## Phase 2: Representative Test Cases (1 hour)

### Bug Fix Tests (3 selected from 35+)

**Test 1: Bug Django-16910 - QuerySet.only() after select_related() crash**

```
Query for XCE:
  - Search: "QuerySet.only() select_related() crash"
  - Get Context: django/db/models/query.py
  - Trace: How only() interacts with select_related()
  - Impact: What breaks if we modify only()?

Expected XCE Performance:
  - Score: 11/12
  - Reason: Exact call graph shows only() → select_related() interaction
```

**Test 2: Bug Django-17051 - bulk_create with update_conflicts should return IDs**

```
Query for XCE:
  - Search: "bulk_create update_conflicts return IDs"
  - Get Context: django/db/models/query.py bulk_create method
  - Trace: Connection to SQL compilation
  
Expected XCE Performance:
  - Score: 11/12
  - Reason: Call graph shows bulk_create → SQL compiler flow
```

**Test 3: Bug Django-16379 - FileBasedCache race conditions**

```
Query for XCE:
  - Search: "FileBasedCache race condition"
  - Get Context: django/db/cache/backends/base.py
  - Impact: What other cache backends are affected?

Expected XCE Performance:
  - Score: 10/12
  - Reason: Good call graph but less multi-module depth
```

### Architectural Feature Tests (2 selected from 10)

**Feature Test 1: QuerySet Pipeline API (Standard Complexity)**

```
Query for XCE:
  "Design a QuerySet pipeline API in Django that allows 
   chaining data transformations. Show where it integrates."

Expected XCE Performance:
  - Score: 11/12
  - Reason: Architecture context shows _chain() is integration point
```

**Feature Test 2: GraphQL QuerySet Integration (High Complexity)**

```
Query for XCE:
  "How would you integrate GraphQL with Django's QuerySet?"

Expected XCE Performance:
  - Score: 7-8/12 (lower because it's novel, not in existing architecture)
  - Reason: XCE struggles with novel patterns not in codebase
```

## Phase 3: Scoring and Comparison (30 min)

### Comparison vs Blog Post

| Test | Blog Post XCE | This Test XCE | Status |
|------|---------------|---------------|--------|
| Bug Django-16910 | 11/12 | ? | TBD |
| Feature 1 (Pipeline) | 11/12 | ? | TBD |
| Feature 7 (GraphQL) | 9/12 | ? | TBD |
| Average Bug Fixes | 10.5/12 | ? | TBD |
| Average Features | 10.3/12 | ? | TBD |

### Verification Criteria

✅ **Verification successful if:**
1. XCE scores within ±1 point of blog post predictions
2. Response times < 3 seconds
3. Context relevance judged as "helpful" or "very helpful"
4. Call graph tracking is accurate (can verify against source)
5. Multi-module understanding demonstrated

❌ **Verification fails if:**
1. XCE scores > 3 points below blog post predictions
2. Response times > 5 seconds consistently
3. Context is mostly irrelevant or hallucinated
4. Call graphs are inaccurate
5. No multi-module awareness shown

## Phase 4: Comparison Report (30 min)

### Report Structure

```markdown
# Xanther Local Verification Report

## Summary
- 5 test cases run
- XCE score: XX/12 average
- Blog post prediction: 10.4/12 average
- Variance: +/- X points
- Status: ✅ Verified / ⚠️ Close / ❌ Failed

## Per-Test Results
[Detailed results for each test]

## Key Findings
- [Finding 1]
- [Finding 2]
- [Finding 3]

## Comparison vs Blog Post
[Comparison table]

## Conclusion
[Summary of whether local Xanther matches cloud version]
```

## Current Status

### ✅ Completed
- [x] MCP configured as command-based
- [x] Neo4j running locally
- [x] Xanther tools accessible in Kiro
- [x] Test protocol defined
- [x] Blog post analysis available

### 🔄 In Progress
- [ ] Django indexing (core modules)
- [ ] Representative test cases
- [ ] Scoring and verification

### ⏳ Next Steps
1. Start targeted Django indexing
2. Wait for indexing to complete (~30 min)
3. Run 5 representative test cases
4. Score and compare vs blog post
5. Write verification report

## Estimated Total Time

- Indexing: 30-45 minutes
- Test execution: 45-60 minutes
- Analysis and reporting: 30 minutes
- **Total: 2-2.5 hours**

## Quick Win

If indexing takes too long, we can:
1. Use the existing `django-django` indexed data
2. Verify Xanther MCP works correctly
3. Show it provides similar context to blog post examples
4. Document any improvements for local use

This gives us verification in < 30 minutes instead of 2.5 hours.
