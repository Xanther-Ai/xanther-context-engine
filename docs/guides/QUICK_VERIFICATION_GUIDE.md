# Quick Verification Guide - 4-Layer Indexing Guarantee

**Purpose**: Quick steps to verify that Xanther's 4-layer indexing guarantee is working  
**Time**: 5-10 minutes per check

## Prerequisites

Ensure these services are running:
- Neo4j at `bolt://localhost:7687` with auth `neo4j:xce_dev_password`
- Dashboard API at `http://localhost:8080`
- MCP Server (if using via Kiro)

## Check 1: Verify Workflow Is Integrated (2 minutes)

### Code Inspection
```bash
cd /Users/rajbhattacharya/Documents/Projects/xanther-context-engine

# Check dashboard is using workflow
grep -n "run_four_layer_indexing" xce/dashboard/server.py
# Expected: Should find import and usage in trigger_index endpoint

# Check workflow file exists
ls -lh xce/indexing/workflow.py
# Expected: File exists, 650+ lines
```

### Visual Inspection
1. Open `xce/dashboard/server.py`
2. Find `@app.post("/api/index", response_model=IndexResponse)`
3. Verify it calls `run_four_layer_indexing(...)` (not `index_repository`)
4. Check that `DocGenerator` and `EmbeddingService` are always initialized (no `if` conditions)

## Check 2: Test Workflow on Small Repository (10 minutes)

### Option A: Unit Test (Fastest)
```bash
cd /Users/rajbhattacharya/Documents/Projects/xanther-context-engine

# Run pytest on workflow tests
python3 -m pytest tests/test_workflow.py -v
# Expected: Should have tests for all 7 nodes
```

### Option B: Manual Test with Small Repo
```bash
# Create a tiny test repository
mkdir -p /tmp/test_repo/src
echo 'def hello(): pass' > /tmp/test_repo/src/test.py

# Index it
python3 << 'EOF'
import asyncio
from xce.indexing.workflow import run_four_layer_indexing
from xce.indexing.doc_generator import DocGenerator
from xce.indexing.embedding import EmbeddingService
from xce.graph.store import GraphStore

async def test():
    # Use test credentials
    graph_store = GraphStore(
        neo4j_uri="bolt://localhost:7687",
        neo4j_auth=("neo4j", "xce_dev_password"),
        embedding_dimensions=512
    )
    
    # These will fail if API keys missing, which is expected
    try:
        doc_generator = DocGenerator(api_key="test-key")
        embedding_service = EmbeddingService(api_key="test-key")
        
        result = await run_four_layer_indexing(
            repo_path="/tmp/test_repo",
            repo_id="test-repo",
            doc_generator=doc_generator,
            embedding_service=embedding_service,
            graph_store=graph_store
        )
        
        print(f"✅ Workflow completed: {result.success}")
        print(f"   Nodes: {len(result.all_nodes)}")
        print(f"   Layer 1 Status: {result.layer_1_status}")
        print(f"   Layer 2 Status: {result.layer_2_status}")
        
    finally:
        await graph_store.close()

asyncio.run(test())
EOF
```

## Check 3: Verify Dashboard Endpoint (2 minutes)

### Using curl
```bash
# Test health check
curl http://localhost:8080/api/health
# Expected: {"status":"healthy","timestamp":"..."}

# List repos
curl http://localhost:8080/api/repositories
# Expected: JSON list of repositories
```

### Using Python
```python
import httpx
import asyncio

async def test():
    async with httpx.AsyncClient() as client:
        # Test health
        resp = await client.get("http://localhost:8080/api/health")
        print(f"Health: {resp.status_code}")
        
        # List repos
        resp = await client.get("http://localhost:8080/api/repositories")
        print(f"Repos: {resp.status_code}")
        data = resp.json()
        print(f"Found {len(data.get('repositories', []))} repositories")

asyncio.run(test())
```

## Check 4: Verify Neo4j Has All Layer Types (5 minutes)

### Query all layer node types
```bash
python3 << 'EOF'
import asyncio
from neo4j import AsyncGraphDatabase

async def check_layers():
    driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "xce_dev_password"))
    
    async with driver.session() as session:
        # Check each layer type exists
        for label in ["ASTNode", "ComponentDesc", "ComponentDoc", "ArchitectureDoc"]:
            result = await session.run(f"MATCH (n:{label}) RETURN count(n) as cnt")
            record = await result.single()
            count = record["cnt"] if record else 0
            print(f"  {label}: {count:,}")
        
        # Check for embeddings
        result = await session.run("MATCH (n)-[r:HAS_EMBEDDING]->() RETURN count(r) as cnt")
        record = await result.single()
        embedding_count = record["cnt"] if record else 0
        print(f"  Embeddings: {embedding_count:,}")
    
    await driver.close()

asyncio.run(check_layers())
EOF

# Expected output (once django-django completes):
#   ASTNode: 87,625
#   ComponentDesc: 87,625
#   ComponentDoc: 28,000+
#   ArchitectureDoc: 150+
#   Embeddings: 87,625
```

## Check 5: Verify Service Initialization Guarantee (3 minutes)

### Read source code
```bash
# Check that services are always initialized
grep -A 20 "@app.post(\"/api/index\"" xce/dashboard/server.py | grep -E "(DocGenerator|EmbeddingService)"

# Expected: Should see:
# doc_generator = DocGenerator(...)  (without if condition)
# embedding_service = EmbeddingService(...)  (without if condition)
```

### Check for conditionals (should have NONE)
```bash
# Look for "if settings.doc_gen" or similar
grep -n "if settings\\.doc" xce/dashboard/server.py
# Expected: No results (should use `or` chaining instead)
```

## Check 6: Monitor Background Indexing (Continuous)

### Check Terminal Status
```bash
# List running processes
ps aux | grep complete_indexing

# Check logs
tail -f /tmp/complete_indexing.log
```

### Expected Progress Pattern
```
2026-06-05 14:40:44 - Connecting to Neo4j
2026-06-05 14:40:44 - Initializing services
2026-06-05 14:40:45 - Fetching existing ASTNode records
2026-06-05 14:40:45 - Found 87625 ASTNode records
2026-06-05 14:40:46 - STEP 2: Generating Component Descriptions
2026-06-05 14:40:46 - Processing batch 1/8763
2026-06-05 14:40:48 - Stored 10 descriptions
  ... (continues for hours)
```

## Verification Checklist

- [ ] Workflow file exists: `xce/indexing/workflow.py` (650+ lines)
- [ ] Dashboard imports workflow: `from xce.indexing.workflow import run_four_layer_indexing`
- [ ] Services always initialized (no conditional logic)
- [ ] Dashboard `/api/index` endpoint healthy
- [ ] Background indexing running (Terminal 30)
- [ ] Neo4j responding to queries
- [ ] Layer node types visible in Neo4j (once indexing completes)

## Success Indicators

✅ **Complete Success**:
- All 4 layer types present in Neo4j (ASTNode, ComponentDesc, ComponentDoc, ArchitectureDoc)
- Embedding relationships created (HAS_EMBEDDING edges)
- All node counts > 0
- Background indexing completes without errors

⚠️ **Partial Success**:
- Layer 1 and 2 present, but 3 and 4 missing = workflow incomplete or failing
- Embeddings present but docs missing = layers skipped
- Nodes match but docs all 0 = doc generation failed

❌ **Failure**:
- Only Layer 1 (AST nodes) present = workflow not running
- Services conditional = not properly integrated
- Background process died = check logs for errors

## Troubleshooting

### If background indexing dies
```bash
# Check the log
tail -50 /tmp/complete_indexing.log

# Common issues:
# - "No nodes found" = Neo4j connectivity issue
# - "API key not found" = Environment variables missing
# - "Memory error" = Batch size too large

# Restart with smaller batches
python3 complete_indexing.py django-django /path/to/django
```

### If services fail to initialize
```bash
# Check environment variables
env | grep -E "OPENROUTER|KIMI"
# Expected: Should show API keys

# Check config
python3 -c "from xce.config import get_settings; s=get_settings(); print(f'API Key: {s.openrouter_api_key or s.kimi_api_key}')"
```

### If workflow fails silently
```bash
# Add debug logging
PYTHONPATH=/path/to/xce python3 -c "
import logging
logging.basicConfig(level=logging.DEBUG)
# then run workflow test
"
```

## Next Steps

1. **Short term (today)**: Monitor background indexing, verify services initialized
2. **Medium term (24-48h)**: Wait for django-django indexing to complete, run verification
3. **Long term**: Test with other repositories, run blog post comparison tests

---

For detailed information, see:
- `TASK_8_IMPLEMENTATION_STATUS.md` - Full implementation details
- `FOUR_LAYER_INDEXING_GUARANTEE.md` - Technical deep dive
- `xce/indexing/workflow.py` - Workflow implementation
