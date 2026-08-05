# Four-Layer Indexing Guarantee for xanther-cli

## Problem Identified

The current `xanther-cli sync --local` workflow **should** run all 4 layers of indexing, but the implementation has a critical issue:

**Current Code Path**:
```
xanther-cli sync --local
  └─→ POST http://localhost:8080/api/index
       └─→ Dashboard Server: trigger_index()
            └─→ index_repository()  ← Should run all 4 layers
```

**The Issue**: The dashboard's `trigger_index()` function tries to check `settings.doc_gen.api_key` and `settings.embedding.api_key`, but the configuration doesn't properly pass these through.

## Solution: Ensure 4-Layer Indexing Always Runs

### Step 1: Create Guaranteed 4-Layer Indexing Workflow

Create a new CLI command that explicitly runs all 4 layers:

**File**: `xanther-cli/src/commands/full-index.ts`

```typescript
import chalk from "chalk";
import ora from "ora";

export async function fullIndexCommand(options: { local?: boolean }) {
  const spinner = ora("Initializing full 4-layer indexing...").start();
  
  try {
    // Step 1: Run Layer 1 (AST Parsing)
    spinner.text = "Layer 1: Parsing AST with tree-sitter...";
    const layer1 = await runLayer1();
    spinner.text = `Layer 1 complete: ${layer1.count} nodes parsed`;
    
    // Step 2: Run Layer 2 (Component Descriptions - LLD Summary)
    spinner.text = "Layer 2: Generating component descriptions...";
    const layer2 = await runLayer2(layer1);
    spinner.text = `Layer 2 complete: ${layer2.count} descriptions generated`;
    
    // Step 3: Run Layer 3 (Component Docs - LLD Detailed)
    spinner.text = "Layer 3: Generating component documentation...";
    const layer3 = await runLayer3(layer2);
    spinner.text = `Layer 3 complete: ${layer3.count} docs generated`;
    
    // Step 4: Run Layer 4 (Architecture - HLD)
    spinner.text = "Layer 4: Generating architecture documentation...";
    const layer4 = await runLayer4(layer3);
    spinner.text = `Layer 4 complete: ${layer4.count} architecture docs`;
    
    // Step 5: Generate Embeddings
    spinner.text = "Embeddings: Generating vector representations...";
    const embeddings = await runEmbeddings(layer1);
    spinner.succeed(`Embeddings complete: ${embeddings.count} vectors generated`);
    
    console.log(`\n  ${chalk.green("✓ 4-Layer Indexing Complete!")}\n`);
    console.log(`  Results:`);
    console.log(`    Layer 1 (AST):             ${chalk.cyan(layer1.count)} nodes`);
    console.log(`    Layer 2 (LLD Summary):     ${chalk.cyan(layer2.count)} descriptions`);
    console.log(`    Layer 3 (LLD Detailed):    ${chalk.cyan(layer3.count)} component docs`);
    console.log(`    Layer 4 (HLD):             ${chalk.cyan(layer4.count)} architecture docs`);
    console.log(`    Embeddings:                ${chalk.cyan(embeddings.count)} vectors\n`);
    
  } catch (err: any) {
    spinner.fail(`Full indexing failed: ${err.message}`);
    process.exit(1);
  }
}
```

### Step 2: Fix Dashboard Server Config

**Update**: `xce/dashboard/server.py` - Fix the `/api/index` endpoint to guarantee all services are initialized:

```python
@app.post("/api/index", response_model=IndexResponse)
async def trigger_index(request: IndexRequest):
    """Trigger local indexing for a repository - GUARANTEED 4-layer."""
    from xce.indexing.indexer import index_repository
    from xce.indexing.embedding import EmbeddingService
    from xce.indexing.doc_generator import DocGenerator
    from xce.config import get_settings
    
    try:
        settings = get_settings()
        
        # Initialize GraphStore
        graph_store = GraphStore(
            neo4j_uri=state.settings.neo4j_uri,
            neo4j_auth=(state.settings.neo4j_user, state.settings.neo4j_password),
            embedding_dimensions=state.settings.embedding_dimensions
        )
        
        # ✅ GUARANTEED: Always initialize doc_generator
        # Uses environment variables from .env
        doc_generator = DocGenerator(
            api_key=settings.openrouter_api_key or settings.kimi_api_key,
            batch_size=state.settings.batch_size,
            model="openai/gpt-4o-mini"  # Explicitly set model
        )
        
        # ✅ GUARANTEED: Always initialize embedding_service
        embedding_service = EmbeddingService(
            api_key=settings.openrouter_api_key or settings.kimi_api_key,
            model="openai/text-embedding-3-small",
            dimensions=1536
        )
        
        # Track progress
        await state.progress_tracker.start_tracking(request.repo_id, 0)
        await state.progress_tracker.update_status(request.repo_id, "indexing")
        
        try:
            # ✅ RUN ALL 4 LAYERS
            result, hashes = await index_repository(
                repo_path=request.repo_path,
                repo_id=request.repo_id,
                doc_generator=doc_generator,        # Layer 2
                embedding_service=embedding_service, # Layer + Embeddings
                graph_store=graph_store,             # Storage
                incremental=request.incremental
            )
            
            # Verify all layers were created
            if result.nodes_count == 0:
                raise ValueError("Layer 1 (AST): No nodes parsed")
            if result.docs_count == 0:
                logger.warning("Layer 2-3 (LLD): No docs generated (may be intentional)")
            if result.embeddings_count == 0:
                logger.warning("Embeddings: No embeddings generated")
            
            await state.progress_tracker.update_status(request.repo_id, "completed")
            
            return IndexResponse(
                status="completed",
                repo_id=request.repo_id,
                nodes_count=result.nodes_count,
                edges_count=result.edges_count,
                docs_count=result.docs_count,
                embeddings_count=result.embeddings_count,
                message=f"4-Layer indexing complete: {result.nodes_count} nodes, {result.edges_count} edges, {result.docs_count} docs, {result.embeddings_count} embeddings"
            )
        finally:
            await graph_store.close()
            
    except Exception as e:
        logger.error(f"Indexing failed: {e}", exc_info=True)
        await state.progress_tracker.update_status(request.repo_id, "failed")
        raise HTTPException(status_code=500, detail=f"Indexing failed: {str(e)}")
```

### Step 3: Create Pre-Defined Workflow Spec

**File**: `.kiro/specs/four-layer-indexing/tasks.md`

```markdown
# Four-Layer Indexing Workflow Specification

## Objective
Ensure every `xanther-cli sync` call runs all 4 layers of indexing + embeddings.

## Tasks

### Task 1: Verify Configuration
- [ ] Check `.env` has OPENROUTER_API_KEY
- [ ] Check Neo4j is running on bolt://localhost:7687
- [ ] Check dashboard server ready on http://localhost:8080

### Task 2: Run Layer 1 (AST Parsing)
- [ ] Parse all source files with tree-sitter
- [ ] Expected: 80k+ nodes for Django
- [ ] Verify: `SELECT COUNT(*) FROM ASTNode`

### Task 3: Run Layer 2 (Component Descriptions)
- [ ] Generate LLM-based summaries
- [ ] Use OpenRouter API
- [ ] Batch size: 10
- [ ] Expected: Same count as Layer 1

### Task 4: Run Layer 3 (Component Docs)
- [ ] Generate detailed documentation
- [ ] For functions/methods only
- [ ] Expected: ~30% of Layer 1 count

### Task 5: Run Layer 4 (Architecture)
- [ ] Generate architecture docs per module
- [ ] Expected: 50-200 docs

### Task 6: Generate Embeddings
- [ ] Create 1536-dim vectors
- [ ] Expected: Same count as Layer 1

### Task 7: Verify All Layers
- [ ] Run verification script
- [ ] All 4 layers should show ✅
```

### Step 4: Create Verification Hook

**New File**: `.kiro/hooks/verify-four-layer-indexing.json`

```json
{
  "name": "Verify Four-Layer Indexing",
  "version": "1.0.0",
  "description": "Verify that all 4 indexing layers completed successfully",
  "when": {
    "type": "postToolUse",
    "toolTypes": ".*index.*"
  },
  "then": {
    "type": "runCommand",
    "command": "python3 /Users/rajbhattacharya/Documents/Projects/xanther-context-engine/verify_indexing_layers.py $REPO_ID"
  }
}
```

### Step 5: Add Console Logging

**Update**: `xce/__main__.py` - Add detailed logging for each layer:

```python
async def cmd_index(args):
    """Index a repository with full 4-layer logging."""
    
    logger.info("="*70)
    logger.info("STARTING FOUR-LAYER INDEXING")
    logger.info("="*70)
    
    logger.info(f"Repository: {args.repo_path}")
    logger.info(f"Repo ID:    {args.repo_id}")
    logger.info(f"Full Mode:  {args.full}")
    
    # ... existing code ...
    
    logger.info("\n" + "="*70)
    logger.info("LAYER 1: AST PARSING (LSP)")
    logger.info("="*70)
    # Parse AST
    logger.info(f"✓ Parsed {len(all_nodes)} nodes")
    
    logger.info("\n" + "="*70)
    logger.info("LAYER 2: COMPONENT DESCRIPTIONS (LLD Summary)")
    logger.info("="*70)
    # Generate descriptions
    logger.info(f"✓ Generated {len(all_descs)} descriptions")
    
    logger.info("\n" + "="*70)
    logger.info("LAYER 3: COMPONENT DOCUMENTATION (LLD Detailed)")
    logger.info("="*70)
    # Generate docs
    logger.info(f"✓ Generated {docs_created} component docs")
    
    logger.info("\n" + "="*70)
    logger.info("LAYER 4: ARCHITECTURE DOCUMENTATION (HLD)")
    logger.info("="*70)
    # Generate architecture
    logger.info(f"✓ Generated {arch_docs_created} architecture docs")
    
    logger.info("\n" + "="*70)
    logger.info("EMBEDDINGS: VECTOR REPRESENTATIONS")
    logger.info("="*70)
    # Generate embeddings
    logger.info(f"✓ Generated {embeddings_count} embeddings")
    
    logger.info("\n" + "="*70)
    logger.info("FOUR-LAYER INDEXING COMPLETE")
    logger.info("="*70)
```

## Implementation Checklist

- [ ] Fix dashboard server `/api/index` to guarantee doc_generator + embedding_service
- [ ] Update xanther-cli sync to display layer progress
- [ ] Create full-index command with explicit layer tracking
- [ ] Add verification hook to confirm all layers
- [ ] Update logging to show each layer completion
- [ ] Document the 4-layer guarantee in README

## Verification Steps

After implementation, verify with:

```bash
# 1. Start services
./neo4j-community-5.26.0/bin/neo4j console &
python3 -m xce.dashboard.server &

# 2. Run CLI with explicit mode
xanther-cli sync --local --full

# 3. Verify all layers
python3 verify_indexing_layers.py django-django
# Should show: ✅ ALL LAYERS COMPLETE

# 4. Check in Kiro
# Should see: Docs count, Embeddings count both > 0
```

## Expected Output

```
Xanther CLI — Sync

Repository: https://github.com/django/django
Branch:     main
Mode:       LOCAL

⚙️  Layer 1: AST Parsing (tree-sitter)        ✓ 87,625 nodes
⚙️  Layer 2: Component Descriptions (LLD-S)   ✓ 87,625 descriptions
⚙️  Layer 3: Component Documentation (LLD-D)  ✓ 28,000 component docs
⚙️  Layer 4: Architecture Documentation (HLD)  ✓ 150 architecture docs
⚙️  Embeddings: Vector Representations         ✓ 87,625 embeddings

✅ Indexing completed - ALL 4 LAYERS COMPLETE

Results:
  Nodes:      87,625
  Edges:      450,000
  Docs:       115,775
  Embeddings: 87,625
```

## Why This Matters

With all 4 layers, Xanther can:
- ✅ Find exact code locations (Layer 1 - what Serena does)
- ✅ Understand what code does (Layers 2-3 - what Auggie does)
- ✅ See architectural implications (Layer 4 - XCE unique advantage)
- ✅ Perform semantic search (Embeddings)
- ✅ Predict impact of changes (Cross-layer analysis)

Without all 4 layers, XCE is just an expensive Serena.

## Timeline

- **Implementation**: 2-3 hours
- **Testing**: 1 hour
- **Documentation**: 1 hour
- **Total**: ~4-5 hours
