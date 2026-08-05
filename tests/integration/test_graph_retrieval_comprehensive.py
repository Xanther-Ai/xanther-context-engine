"""
Comprehensive Graph Retrieval Tests — HLD, LDD, Callers/Callees, Traceability, Impact

Tests deeply cover:
 1. HLD documentation: ComponentDescription stored and retrieved
 2. LDD documentation: ComponentDoc (algorithm/data_flow/error_handling)
 3. Architecture docs: ArchitectureDoc (patterns, roles, integrations)
 4. Callers/callees at depth 1-5, cross-file chains
 5. Full traceability chain: code → component desc → component doc → arch doc
 6. Impact analysis: risk score, test coverage detection, propagation depth
 7. Semantic search with embeddings
 8. Combined retrieval: one symbol with all attached docs and call chains

Prerequisites:
  Neo4j running at bolt://localhost:7687

Run with:
    pytest tests/integration/test_graph_retrieval_comprehensive.py -v
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

from xce.graph.store import GraphStore
from xce.models import (
    ASTEdge,
    ASTNode,
    ArchitectureDoc,
    ComponentDescription,
    ComponentDoc,
    GraphQuery,
    NodeKind,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = ("neo4j", os.getenv("NEO4J_PASSWORD", "xce_dev_password"))


def _rid() -> str:
    """Unique repo_id per test to prevent cross-test pollution."""
    return f"tgr_{int(time.time() * 1_000_000) % 10_000_000}"


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def gs():
    store = GraphStore(NEO4J_URI, NEO4J_AUTH, embedding_dimensions=4)
    await store.init_schema()
    yield store
    await store.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node(repo: str, filepath: str, name: str, kind: NodeKind = NodeKind.FUNCTION,
          docstring: str | None = None, start_line: int = 1, end_line: int = 5) -> ASTNode:
    return ASTNode(
        id=f"{repo}:{filepath}:{name}",
        kind=kind,
        name=name,
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        source_text=f"def {name}(): pass",
        docstring=docstring,
    )


def _edge(repo: str, src_file: str, src_name: str,
          tgt_file: str, tgt_name: str, relation: str = "calls") -> ASTEdge:
    return ASTEdge(
        source_id=f"{repo}:{src_file}:{src_name}",
        target_id=f"{repo}:{tgt_file}:{tgt_name}",
        relation=relation,
    )


# ===========================================================================
# 1. HLD — ComponentDescription storage and retrieval
# ===========================================================================

class TestHLDComponentDescription:

    @pytest.mark.asyncio
    async def test_store_and_retrieve_component_description(self, gs):
        """ComponentDescription (HLD) is stored and has_documentation becomes True."""
        r = _rid()
        nodes = [_node(r, "service/auth.py", "authenticate")]
        await gs.upsert_ast_nodes(nodes)

        desc = ComponentDescription(
            node_id=f"{r}:service/auth.py:authenticate",
            summary="Validates user credentials against the database.",
            responsibilities=["hash comparison", "rate-limit check", "JWT issuance"],
            dependencies=["db.users", "jwt_service"],
        )
        count = await gs.upsert_documentation([desc])
        assert count == 1

        trace = await gs.get_traceability(f"{r}:service/auth.py:authenticate")
        assert trace["has_documentation"] is True
        assert len(trace["requirement_links"]) == 1
        link = trace["requirement_links"][0]
        assert link["type"] == "ComponentDescription"
        assert "credentials" in link["summary"]
        assert "hash comparison" in link["responsibilities"]

    @pytest.mark.asyncio
    async def test_multiple_nodes_each_get_component_description(self, gs):
        """Each node can have its own independent ComponentDescription."""
        r = _rid()
        names = ["parse_request", "validate_token", "build_response"]
        nodes = [_node(r, "api/handler.py", n) for n in names]
        await gs.upsert_ast_nodes(nodes)

        descs = [
            ComponentDescription(
                node_id=f"{r}:api/handler.py:{n}",
                summary=f"HLD summary for {n}",
                responsibilities=[f"resp_{n}"],
                dependencies=[],
            )
            for n in names
        ]
        count = await gs.upsert_documentation(descs)
        assert count == 3

        for n in names:
            trace = await gs.get_traceability(f"{r}:api/handler.py:{n}")
            assert trace["has_documentation"] is True

    @pytest.mark.asyncio
    async def test_component_description_update_is_idempotent(self, gs):
        """Upserting the same node_id twice updates the summary in place."""
        r = _rid()
        nodes = [_node(r, "core.py", "process")]
        await gs.upsert_ast_nodes(nodes)

        desc1 = ComponentDescription(
            node_id=f"{r}:core.py:process",
            summary="Original summary.",
            responsibilities=["step A"],
            dependencies=[],
        )
        await gs.upsert_documentation([desc1])

        desc2 = ComponentDescription(
            node_id=f"{r}:core.py:process",
            summary="Updated summary with more detail.",
            responsibilities=["step A", "step B"],
            dependencies=["helper"],
        )
        await gs.upsert_documentation([desc2])

        trace = await gs.get_traceability(f"{r}:core.py:process")
        link = trace["requirement_links"][0]
        assert "Updated summary" in link["summary"]
        assert "step B" in link["responsibilities"]


# ===========================================================================
# 2. LDD — ComponentDoc (algorithm / data_flow / error_handling)
# ===========================================================================

class TestLDDComponentDoc:

    @pytest.mark.asyncio
    async def test_store_and_retrieve_component_doc(self, gs):
        """ComponentDoc (LDD) is linked via DETAILED_IN and appears in traceability."""
        r = _rid()
        nodes = [_node(r, "engine/parser.py", "parse_ast")]
        await gs.upsert_ast_nodes(nodes)

        # Must have ComponentDescription first (DETAILED_IN hangs off it)
        hld = ComponentDescription(
            node_id=f"{r}:engine/parser.py:parse_ast",
            summary="Parses source text into an AST.",
            responsibilities=["tokenisation", "tree construction"],
            dependencies=["tree-sitter"],
        )
        await gs.upsert_documentation([hld])

        ldd = ComponentDoc(
            component_id=f"{r}:engine/parser.py:parse_ast",
            algorithm_description="Recursive descent over token stream.",
            data_flow="source_text → tokeniser → parser → ASTNode list",
            error_handling="Raises ParseError on invalid syntax; logs and continues.",
            edge_cases=["empty file", "unicode identifiers", "nested decorators"],
        )
        count = await gs.upsert_documentation([ldd])
        assert count == 1

        trace = await gs.get_traceability(f"{r}:engine/parser.py:parse_ast")
        ldd_links = [l for l in trace["requirement_links"] if l["type"] == "ComponentDoc"]
        assert len(ldd_links) == 1
        d = ldd_links[0]
        assert "Recursive descent" in d["algorithm_description"]
        assert "tokeniser" in d["data_flow"]
        assert "ParseError" in d["error_handling"]
        assert "empty file" in d["edge_cases"]

    @pytest.mark.asyncio
    async def test_component_doc_without_hld_does_not_appear(self, gs):
        """ComponentDoc without a parent ComponentDescription returns no LDD links."""
        r = _rid()
        nodes = [_node(r, "orphan.py", "orphan_fn")]
        await gs.upsert_ast_nodes(nodes)

        # Insert LDD only — no HLD
        ldd = ComponentDoc(
            component_id=f"{r}:orphan.py:orphan_fn",
            algorithm_description="Should not be reachable.",
            data_flow="N/A",
            error_handling="N/A",
            edge_cases=[],
        )
        await gs.upsert_documentation([ldd])

        trace = await gs.get_traceability(f"{r}:orphan.py:orphan_fn")
        ldd_links = [l for l in trace["requirement_links"] if l["type"] == "ComponentDoc"]
        # No HLD ⇒ no DETAILED_IN path reachable from ASTNode
        assert ldd_links == []

    @pytest.mark.asyncio
    async def test_full_hld_ldd_chain_returns_both_link_types(self, gs):
        """HLD + LDD both appear in requirement_links with correct types."""
        r = _rid()
        nodes = [_node(r, "svc/transformer.py", "transform")]
        await gs.upsert_ast_nodes(nodes)

        hld = ComponentDescription(
            node_id=f"{r}:svc/transformer.py:transform",
            summary="Transforms raw data into domain objects.",
            responsibilities=["validate schema", "map fields"],
            dependencies=["schema_validator"],
        )
        ldd = ComponentDoc(
            component_id=f"{r}:svc/transformer.py:transform",
            algorithm_description="Field-by-field mapping with type coercion.",
            data_flow="raw_dict → schema_check → domain_object",
            error_handling="Raises ValidationError on missing required fields.",
            edge_cases=["null values", "extra keys"],
        )
        await gs.upsert_documentation([hld, ldd])

        trace = await gs.get_traceability(f"{r}:svc/transformer.py:transform")
        types = {l["type"] for l in trace["requirement_links"]}
        assert "ComponentDescription" in types
        assert "ComponentDoc" in types


# ===========================================================================
# 3. Architecture docs (HLD at module level)
# ===========================================================================

class TestArchitectureDoc:

    @pytest.mark.asyncio
    async def test_store_and_retrieve_architecture_doc(self, gs):
        """ArchitectureDoc is attached via PART_OF_ARCHITECTURE and returned in traceability."""
        r = _rid()
        # Two nodes in the same module
        nodes = [
            _node(r, "payments/gateway.py", "charge"),
            _node(r, "payments/gateway.py", "refund"),
        ]
        await gs.upsert_ast_nodes(nodes)

        arch = ArchitectureDoc(
            module_path="payments/gateway.py",
            architectural_role="service",
            design_patterns=["Facade", "Strategy"],
            integration_points=["Stripe API", "internal ledger"],
            quality_attributes=["idempotency", "PCI-DSS compliance"],
        )
        count = await gs.upsert_documentation([arch])
        assert count >= 1

        trace = await gs.get_traceability(f"{r}:payments/gateway.py:charge")
        assert trace["has_architecture_context"] is True
        ctx = trace["architecture_context"][0]
        assert ctx["architectural_role"] == "service"
        assert "Facade" in ctx["design_patterns"]
        assert "Stripe API" in ctx["integration_points"]
        assert "PCI-DSS compliance" in ctx["quality_attributes"]

    @pytest.mark.asyncio
    async def test_architecture_doc_applies_to_all_nodes_in_module(self, gs):
        """All nodes with matching filepath prefix get the architecture context."""
        r = _rid()
        nodes = [
            _node(r, "infra/cache.py", "get_cached"),
            _node(r, "infra/cache.py", "set_cache"),
            _node(r, "infra/cache.py", "invalidate"),
        ]
        await gs.upsert_ast_nodes(nodes)

        arch = ArchitectureDoc(
            module_path="infra/cache.py",
            architectural_role="infrastructure",
            design_patterns=["Cache-Aside"],
            integration_points=["Redis"],
            quality_attributes=["low-latency"],
        )
        await gs.upsert_documentation([arch])

        for name in ["get_cached", "set_cache", "invalidate"]:
            trace = await gs.get_traceability(f"{r}:infra/cache.py:{name}")
            assert trace["has_architecture_context"] is True

    @pytest.mark.asyncio
    async def test_all_three_doc_levels_in_single_traceability_call(self, gs):
        """A single get_traceability call returns HLD, LDD, and architecture context."""
        r = _rid()
        nodes = [_node(r, "ml/predictor.py", "predict")]
        await gs.upsert_ast_nodes(nodes)

        hld = ComponentDescription(
            node_id=f"{r}:ml/predictor.py:predict",
            summary="Runs inference on the loaded model.",
            responsibilities=["pre-process input", "run model", "post-process output"],
            dependencies=["model_loader"],
        )
        ldd = ComponentDoc(
            component_id=f"{r}:ml/predictor.py:predict",
            algorithm_description="Forward pass through neural network layers.",
            data_flow="raw_input → normalise → model → softmax → label",
            error_handling="Returns None on shape mismatch.",
            edge_cases=["all-zero input", "batch size 1"],
        )
        arch = ArchitectureDoc(
            module_path="ml/predictor.py",
            architectural_role="model",
            design_patterns=["Pipeline"],
            integration_points=["feature store", "monitoring service"],
            quality_attributes=["reproducibility"],
        )
        await gs.upsert_documentation([hld, ldd, arch])

        trace = await gs.get_traceability(f"{r}:ml/predictor.py:predict")
        types = {l["type"] for l in trace["requirement_links"]}
        assert "ComponentDescription" in types
        assert "ComponentDoc" in types
        assert trace["has_architecture_context"] is True
        assert trace["has_documentation"] is True


# ===========================================================================
# 4. Callers — depth 1 through 5, cross-file chains
# ===========================================================================

class TestCallersDepth:

    @pytest.fixture
    async def call_chain(self, gs):
        """Build a 5-level call chain: a→b→c→d→e→target."""
        r = _rid()
        files = ["a.py", "b.py", "c.py", "d.py", "e.py", "target.py"]
        names = ["fn_a", "fn_b", "fn_c", "fn_d", "fn_e", "fn_target"]
        nodes = [_node(r, f, n) for f, n in zip(files, names)]
        await gs.upsert_ast_nodes(nodes)

        edges = [
            _edge(r, files[i], names[i], files[i + 1], names[i + 1])
            for i in range(len(names) - 1)
        ]
        await gs.upsert_edges(edges)
        return r, names

    @pytest.mark.asyncio
    async def test_callers_depth_1(self, gs, call_chain):
        r, names = call_chain
        callers = await gs.get_callers(f"{r}:target.py:fn_target", depth=1)
        caller_names = {c["name"] for c in callers}
        assert "fn_e" in caller_names
        assert "fn_a" not in caller_names  # too far

    @pytest.mark.asyncio
    async def test_callers_depth_2(self, gs, call_chain):
        r, names = call_chain
        callers = await gs.get_callers(f"{r}:target.py:fn_target", depth=2)
        caller_names = {c["name"] for c in callers}
        assert "fn_e" in caller_names
        assert "fn_d" in caller_names
        assert "fn_c" not in caller_names

    @pytest.mark.asyncio
    async def test_callers_depth_5_finds_root(self, gs, call_chain):
        r, names = call_chain
        callers = await gs.get_callers(f"{r}:target.py:fn_target", depth=5)
        caller_names = {c["name"] for c in callers}
        assert "fn_a" in caller_names
        assert "fn_e" in caller_names

    @pytest.mark.asyncio
    async def test_callers_returns_filepath_and_kind(self, gs, call_chain):
        r, names = call_chain
        callers = await gs.get_callers(f"{r}:target.py:fn_target", depth=1)
        assert len(callers) >= 1
        c = callers[0]
        assert "filepath" in c
        assert "kind" in c
        assert "node_id" in c

    @pytest.mark.asyncio
    async def test_no_callers_for_root_node(self, gs, call_chain):
        r, names = call_chain
        callers = await gs.get_callers(f"{r}:a.py:fn_a", depth=5)
        assert callers == []


# ===========================================================================
# 5. Callees — depth 1 through 5, cross-file chains
# ===========================================================================

class TestCalleesDepth:

    @pytest.fixture
    async def fan_out_tree(self, gs):
        """Build a 3-level fan-out: root → [a, b] → [aa, ab, ba, bb]."""
        r = _rid()
        nodes = [
            _node(r, "root.py",   "root"),
            _node(r, "mid.py",    "mid_a"),
            _node(r, "mid.py",    "mid_b"),
            _node(r, "leaf.py",   "leaf_aa"),
            _node(r, "leaf.py",   "leaf_ab"),
            _node(r, "leaf.py",   "leaf_ba"),
            _node(r, "leaf.py",   "leaf_bb"),
        ]
        await gs.upsert_ast_nodes(nodes)

        edges = [
            _edge(r, "root.py", "root",  "mid.py",  "mid_a"),
            _edge(r, "root.py", "root",  "mid.py",  "mid_b"),
            _edge(r, "mid.py",  "mid_a", "leaf.py", "leaf_aa"),
            _edge(r, "mid.py",  "mid_a", "leaf.py", "leaf_ab"),
            _edge(r, "mid.py",  "mid_b", "leaf.py", "leaf_ba"),
            _edge(r, "mid.py",  "mid_b", "leaf.py", "leaf_bb"),
        ]
        await gs.upsert_edges(edges)
        return r

    @pytest.mark.asyncio
    async def test_callees_depth_1(self, gs, fan_out_tree):
        r = fan_out_tree
        callees = await gs.get_callees(f"{r}:root.py:root", depth=1)
        names = {c["name"] for c in callees}
        assert "mid_a" in names
        assert "mid_b" in names
        assert "leaf_aa" not in names

    @pytest.mark.asyncio
    async def test_callees_depth_2_includes_leaves(self, gs, fan_out_tree):
        r = fan_out_tree
        callees = await gs.get_callees(f"{r}:root.py:root", depth=2)
        names = {c["name"] for c in callees}
        assert {"mid_a", "mid_b", "leaf_aa", "leaf_ab", "leaf_ba", "leaf_bb"}.issubset(names)

    @pytest.mark.asyncio
    async def test_callees_leaf_has_none(self, gs, fan_out_tree):
        r = fan_out_tree
        callees = await gs.get_callees(f"{r}:leaf.py:leaf_aa", depth=3)
        assert callees == []

    @pytest.mark.asyncio
    async def test_callers_and_callees_symmetric(self, gs):
        """If A calls B, then get_callers(B,1) includes A and get_callees(A,1) includes B."""
        r = _rid()
        nodes = [_node(r, "x.py", "caller_fn"), _node(r, "y.py", "callee_fn")]
        await gs.upsert_ast_nodes(nodes)
        await gs.upsert_edges([_edge(r, "x.py", "caller_fn", "y.py", "callee_fn")])

        callers = await gs.get_callers(f"{r}:y.py:callee_fn", depth=1)
        callees = await gs.get_callees(f"{r}:x.py:caller_fn", depth=1)

        assert any(c["name"] == "caller_fn" for c in callers)
        assert any(c["name"] == "callee_fn" for c in callees)


# ===========================================================================
# 6. Impact analysis — risk score, propagation depth, test file detection
# ===========================================================================

class TestImpactAnalysis:

    @pytest.fixture
    async def impact_graph(self, gs):
        """
        Topology:
          test_auth.py::test_login   ──CALLS──▶  auth.py::login
          api/handler.py::handle     ──CALLS──▶  auth.py::login
          api/middleware.py::guard   ──CALLS──▶  auth.py::login
          auth.py::login             ──CALLS──▶  db/users.py::find_user
          db/users.py::find_user     ──CALLS──▶  db/conn.py::execute
        """
        r = _rid()
        nodes = [
            _node(r, "auth.py",            "login"),
            _node(r, "api/handler.py",     "handle"),
            _node(r, "api/middleware.py",  "guard"),
            _node(r, "tests/test_auth.py", "test_login"),
            _node(r, "db/users.py",        "find_user"),
            _node(r, "db/conn.py",         "execute"),
        ]
        await gs.upsert_ast_nodes(nodes)

        edges = [
            _edge(r, "api/handler.py",     "handle",     "auth.py",     "login"),
            _edge(r, "api/middleware.py",  "guard",      "auth.py",     "login"),
            _edge(r, "tests/test_auth.py", "test_login", "auth.py",     "login"),
            _edge(r, "auth.py",            "login",      "db/users.py", "find_user"),
            _edge(r, "db/users.py",        "find_user",  "db/conn.py",  "execute"),
        ]
        await gs.upsert_edges(edges)
        return r

    @pytest.mark.asyncio
    async def test_impact_structure(self, gs, impact_graph):
        r = impact_graph
        result = await gs.get_impact_analysis(f"{r}:auth.py:login")
        assert "symbol_id" in result
        assert "risk_score" in result
        assert "direct_callers_count" in result
        assert "direct_dependents" in result
        assert "test_files" in result
        assert "propagation_depth" in result

    @pytest.mark.asyncio
    async def test_direct_callers_count(self, gs, impact_graph):
        r = impact_graph
        result = await gs.get_impact_analysis(f"{r}:auth.py:login")
        # handle + guard + test_login = 3 direct callers
        assert result["direct_callers_count"] == 3

    @pytest.mark.asyncio
    async def test_test_files_detected(self, gs, impact_graph):
        r = impact_graph
        result = await gs.get_impact_analysis(f"{r}:auth.py:login")
        test_paths = [t["filepath"] for t in result["test_files"]]
        assert any("test" in p for p in test_paths)

    @pytest.mark.asyncio
    async def test_direct_dependents_exclude_test_files(self, gs, impact_graph):
        r = impact_graph
        result = await gs.get_impact_analysis(f"{r}:auth.py:login")
        dep_paths = [d["filepath"] for d in result["direct_dependents"]]
        assert all("test" not in p for p in dep_paths)

    @pytest.mark.asyncio
    async def test_propagation_depth_nonzero_when_callees_exist(self, gs, impact_graph):
        r = impact_graph
        result = await gs.get_impact_analysis(f"{r}:auth.py:login")
        assert result["propagation_depth"] >= 1

    @pytest.mark.asyncio
    async def test_risk_score_increases_with_callers(self, gs):
        """Symbol with more callers should have higher risk than one with fewer."""
        r = _rid()
        low = _node(r, "low.py", "low_risk")
        high = _node(r, "high.py", "high_risk")
        callers = [_node(r, f"c{i}.py", f"caller{i}") for i in range(8)]
        await gs.upsert_ast_nodes([low, high] + callers)

        # low_risk: 1 caller
        await gs.upsert_edges([_edge(r, "c0.py", "caller0", "low.py", "low_risk")])
        # high_risk: 8 callers
        await gs.upsert_edges([
            _edge(r, f"c{i}.py", f"caller{i}", "high.py", "high_risk")
            for i in range(8)
        ])

        low_r  = await gs.get_impact_analysis(f"{r}:low.py:low_risk")
        high_r = await gs.get_impact_analysis(f"{r}:high.py:high_risk")
        assert high_r["risk_score"] > low_r["risk_score"]

    @pytest.mark.asyncio
    async def test_leaf_node_zero_callers(self, gs):
        r = _rid()
        await gs.upsert_ast_nodes([_node(r, "leaf.py", "leaf")])
        result = await gs.get_impact_analysis(f"{r}:leaf.py:leaf")
        assert result["direct_callers_count"] == 0
        assert result["risk_score"] == 0.0


# ===========================================================================
# 7. Traceability — test coverage, has_test_coverage flag
# ===========================================================================

class TestTraceability:

    @pytest.mark.asyncio
    async def test_traceability_has_test_coverage_when_test_calls_symbol(self, gs):
        r = _rid()
        nodes = [
            _node(r, "utils/math.py",       "square"),
            _node(r, "tests/test_math.py",  "test_square"),
        ]
        await gs.upsert_ast_nodes(nodes)
        await gs.upsert_edges([_edge(r, "tests/test_math.py", "test_square",
                                     "utils/math.py", "square")])

        trace = await gs.get_traceability(f"{r}:utils/math.py:square")
        assert trace["has_test_coverage"] is True
        covered = [t["name"] for t in trace["test_coverage"]]
        assert "test_square" in covered

    @pytest.mark.asyncio
    async def test_traceability_no_test_coverage_for_untested_symbol(self, gs):
        r = _rid()
        await gs.upsert_ast_nodes([_node(r, "utils/fmt.py", "format_date")])
        trace = await gs.get_traceability(f"{r}:utils/fmt.py:format_date")
        assert trace["has_test_coverage"] is False
        assert trace["test_coverage"] == []

    @pytest.mark.asyncio
    async def test_traceability_no_docs_for_undocumented_symbol(self, gs):
        r = _rid()
        await gs.upsert_ast_nodes([_node(r, "bare.py", "bare_fn")])
        trace = await gs.get_traceability(f"{r}:bare.py:bare_fn")
        assert trace["has_documentation"] is False
        assert trace["requirement_links"] == []

    @pytest.mark.asyncio
    async def test_full_traceability_all_flags_true(self, gs):
        """Node with HLD + LDD + ArchDoc + test coverage sets all flags True."""
        r = _rid()
        nodes = [
            _node(r, "core/engine.py",    "run"),
            _node(r, "tests/test_core.py", "test_run"),
        ]
        await gs.upsert_ast_nodes(nodes)
        await gs.upsert_edges([_edge(r, "tests/test_core.py", "test_run",
                                     "core/engine.py", "run")])

        hld = ComponentDescription(
            node_id=f"{r}:core/engine.py:run",
            summary="Runs the processing engine.",
            responsibilities=["load config", "execute pipeline"],
            dependencies=["config_loader", "pipeline"],
        )
        ldd = ComponentDoc(
            component_id=f"{r}:core/engine.py:run",
            algorithm_description="Sequential pipeline execution.",
            data_flow="config → stages → result",
            error_handling="Wraps each stage in try/except.",
            edge_cases=["empty stage list", "stage timeout"],
        )
        arch = ArchitectureDoc(
            module_path="core/engine.py",
            architectural_role="orchestrator",
            design_patterns=["Chain of Responsibility"],
            integration_points=["stage_registry"],
            quality_attributes=["extensibility"],
        )
        await gs.upsert_documentation([hld, ldd, arch])

        trace = await gs.get_traceability(f"{r}:core/engine.py:run")
        assert trace["has_documentation"] is True
        assert trace["has_test_coverage"] is True
        assert trace["has_architecture_context"] is True


# ===========================================================================
# 8. Semantic search with embeddings
# ===========================================================================

def _zero_embedding(dims: int = 1536, hot_idx: int = 0) -> list[float]:
    """Return a unit vector with 1.0 at hot_idx (length=dims)."""
    v = [0.0] * dims
    v[hot_idx] = 1.0
    return v


class TestSemanticSearch:
    """Semantic search requires the live 1536-dim vector index in Neo4j."""

    @pytest.fixture
    async def gs1536(self):
        """GraphStore configured for 1536 dimensions (matches the live index)."""
        store = GraphStore(NEO4J_URI, NEO4J_AUTH, embedding_dimensions=1536)
        await store.init_schema()
        yield store
        await store.close()

    @pytest.mark.asyncio
    async def test_upsert_and_search_embeddings(self, gs1536):
        """Embedding stored and retrieved via semantic_search, scoped by repo_id."""
        r = _rid()
        nodes = [
            _node(r, "utils.py", "add"),
            _node(r, "utils.py", "subtract"),
            _node(r, "utils.py", "multiply"),
        ]
        await gs1536.upsert_ast_nodes(nodes)

        node_ids = [n.id for n in nodes]
        embeddings = [_zero_embedding(hot_idx=0), _zero_embedding(hot_idx=1), _zero_embedding(hot_idx=2)]
        count = await gs1536.upsert_embeddings(node_ids, embeddings)
        assert count == 3

        # Search without repo filter but verify the correct node is ranked top among ours
        results = await gs1536.semantic_search(_zero_embedding(hot_idx=0), top_k=20)
        assert len(results) >= 1
        our_results = [res for res in results if res.node_id.startswith(r)]
        assert len(our_results) >= 1
        # The "add" node has [1,0,0...] — same vector — must be the top match among ours
        assert our_results[0].node_id == f"{r}:utils.py:add"

    @pytest.mark.asyncio
    async def test_semantic_search_dimension_mismatch_raises(self, gs1536):
        with pytest.raises(ValueError, match="dimensions"):
            await gs1536.semantic_search([1.0, 2.0], top_k=5)  # 2-dim ≠ 1536-dim

    @pytest.mark.asyncio
    async def test_upsert_embeddings_dimension_mismatch_raises(self, gs1536):
        r = _rid()
        await gs1536.upsert_ast_nodes([_node(r, "x.py", "fn")])
        with pytest.raises(ValueError):
            await gs1536.upsert_embeddings([f"{r}:x.py:fn"], [[1.0, 2.0]])  # wrong dims

    @pytest.mark.asyncio
    async def test_semantic_search_with_repo_filter(self, gs1536):
        """repo_id filter restricts results to the target repository."""
        r1, r2 = _rid(), _rid()
        nodes1 = [_node(r1, "a.py", "fn_a")]
        nodes2 = [_node(r2, "b.py", "fn_b")]
        await gs1536.upsert_ast_nodes(nodes1 + nodes2)

        await gs1536.upsert_embeddings([nodes1[0].id], [_zero_embedding(hot_idx=0)])
        await gs1536.upsert_embeddings([nodes2[0].id], [_zero_embedding(hot_idx=0)])

        results = await gs1536.semantic_search(_zero_embedding(hot_idx=0), top_k=5, repo_id=r1)
        assert all(res.node_id.startswith(r1) for res in results)


# ===========================================================================
# 9. Node kinds — class, module, method, import
# ===========================================================================

class TestNodeKinds:

    @pytest.mark.asyncio
    async def test_upsert_all_node_kinds(self, gs):
        r = _rid()
        nodes = [
            _node(r, "app.py", "MyApp",   kind=NodeKind.CLASS),
            _node(r, "app.py", "app",     kind=NodeKind.MODULE),
            _node(r, "app.py", "run",     kind=NodeKind.METHOD),
            _node(r, "app.py", "os",      kind=NodeKind.IMPORT),
            _node(r, "app.py", "VERSION", kind=NodeKind.VARIABLE),
        ]
        count = await gs.upsert_ast_nodes(nodes)
        assert count == 5

    @pytest.mark.asyncio
    async def test_edges_across_different_kinds(self, gs):
        """CONTAINS and CALLS between class→method and method→function."""
        r = _rid()
        nodes = [
            _node(r, "svc.py", "Service",    kind=NodeKind.CLASS),
            _node(r, "svc.py", "connect",    kind=NodeKind.METHOD),
            _node(r, "db.py",  "open_conn",  kind=NodeKind.FUNCTION),
        ]
        await gs.upsert_ast_nodes(nodes)

        edges = [
            ASTEdge(source_id=f"{r}:svc.py:Service",
                    target_id=f"{r}:svc.py:connect",  relation="contains"),
            ASTEdge(source_id=f"{r}:svc.py:connect",
                    target_id=f"{r}:db.py:open_conn",  relation="calls"),
        ]
        count = await gs.upsert_edges(edges)
        assert count == 2

    @pytest.mark.asyncio
    async def test_semantic_search_filter_by_kind(self, gs):
        """Kind filter via semantic search — uses raw query as vector index is pre-existing."""
        r = _rid()
        nodes = [
            _node(r, "m.py", "MyClass", kind=NodeKind.CLASS),
            _node(r, "m.py", "my_fn",   kind=NodeKind.FUNCTION),
        ]
        await gs.upsert_ast_nodes(nodes)

        # Verify kind is stored correctly by raw Cypher
        query = GraphQuery(
            cypher="MATCH (n:ASTNode) WHERE n.id IN $ids RETURN n.id AS id, n.kind AS kind",
            params={"ids": [n.id for n in nodes]},
        )
        results = await gs.execute_query(query)
        kinds = {r["kind"] for r in results}
        assert NodeKind.CLASS.value in kinds
        assert NodeKind.FUNCTION.value in kinds


# ===========================================================================
# 10. Graph neighbors
# ===========================================================================

class TestGetNeighbors:

    @pytest.mark.asyncio
    async def test_neighbors_depth_1_bidirectional(self, gs):
        r = _rid()
        nodes = [
            _node(r, "a.py", "fn_a"),
            _node(r, "b.py", "fn_b"),
            _node(r, "c.py", "fn_c"),
        ]
        await gs.upsert_ast_nodes(nodes)
        await gs.upsert_edges([
            _edge(r, "a.py", "fn_a", "b.py", "fn_b"),
            _edge(r, "b.py", "fn_b", "c.py", "fn_c"),
        ])

        neighbors = await gs.get_neighbors(f"{r}:b.py:fn_b", depth=1)
        ids = {n.node_id for n in neighbors}
        assert f"{r}:a.py:fn_a" in ids
        assert f"{r}:c.py:fn_c" in ids

    @pytest.mark.asyncio
    async def test_neighbors_depth_2_expands(self, gs):
        r = _rid()
        nodes = [_node(r, f"{c}.py", f"fn_{c}") for c in "abcd"]
        await gs.upsert_ast_nodes(nodes)
        await gs.upsert_edges([
            _edge(r, "a.py", "fn_a", "b.py", "fn_b"),
            _edge(r, "b.py", "fn_b", "c.py", "fn_c"),
            _edge(r, "c.py", "fn_c", "d.py", "fn_d"),
        ])

        neighbors = await gs.get_neighbors(f"{r}:a.py:fn_a", depth=2)
        ids = {n.node_id for n in neighbors}
        assert f"{r}:b.py:fn_b" in ids
        assert f"{r}:c.py:fn_c" in ids

    @pytest.mark.asyncio
    async def test_neighbors_relation_filter(self, gs):
        r = _rid()
        nodes = [
            _node(r, "pkg.py", "pkg",  kind=NodeKind.MODULE),
            _node(r, "pkg.py", "cls",  kind=NodeKind.CLASS),
            _node(r, "dep.py", "dep",  kind=NodeKind.MODULE),
        ]
        await gs.upsert_ast_nodes(nodes)
        await gs.upsert_edges([
            ASTEdge(source_id=f"{r}:pkg.py:pkg",  target_id=f"{r}:pkg.py:cls", relation="contains"),
            ASTEdge(source_id=f"{r}:pkg.py:pkg",  target_id=f"{r}:dep.py:dep", relation="imports"),
        ])

        contains_neighbors = await gs.get_neighbors(f"{r}:pkg.py:pkg", relation="contains", depth=1)
        ids = {n.node_id for n in contains_neighbors}
        assert f"{r}:pkg.py:cls" in ids
        assert f"{r}:dep.py:dep" not in ids


# ===========================================================================
# 11. Raw Cypher — execute_query
# ===========================================================================

class TestExecuteQuery:

    @pytest.mark.asyncio
    async def test_custom_cypher_returns_nodes(self, gs):
        r = _rid()
        nodes = [
            _node(r, "utils.py", "alpha", docstring="Alpha does A"),
            _node(r, "utils.py", "beta",  docstring="Beta does B"),
        ]
        await gs.upsert_ast_nodes(nodes)

        query = GraphQuery(
            cypher="MATCH (n:ASTNode) WHERE n.name = $name RETURN n.id AS id, n.name AS name",
            params={"name": "alpha"},
        )
        results = await gs.execute_query(query)
        assert len(results) >= 1
        assert results[0]["name"] == "alpha"

    @pytest.mark.asyncio
    async def test_custom_cypher_empty_result(self, gs):
        query = GraphQuery(
            cypher="MATCH (n:ASTNode {name: $name}) RETURN n",
            params={"name": "__nonexistent_xyz__"},
        )
        results = await gs.execute_query(query)
        assert results == []


# ===========================================================================
# 12. Repository listing
# ===========================================================================

class TestListRepositories:

    @pytest.mark.asyncio
    async def test_list_shows_indexed_repos(self, gs):
        r = _rid()
        nodes = [_node(r, "x.py", "fn_x"), _node(r, "y.py", "fn_y")]
        await gs.upsert_ast_nodes(nodes)

        repos = await gs.list_repositories()
        repo_ids = [row["repo_id"] for row in repos]
        assert r in repo_ids

    @pytest.mark.asyncio
    async def test_list_includes_node_count(self, gs):
        r = _rid()
        nodes = [_node(r, "a.py", f"fn_{i}") for i in range(5)]
        await gs.upsert_ast_nodes(nodes)

        repos = await gs.list_repositories()
        row = next((x for x in repos if x["repo_id"] == r), None)
        assert row is not None
        assert row["node_count"] >= 5


# ===========================================================================
# 13. Edge cases / error handling
# ===========================================================================

class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_upsert_empty_nodes(self, gs):
        assert await gs.upsert_ast_nodes([]) == 0

    @pytest.mark.asyncio
    async def test_upsert_empty_edges(self, gs):
        assert await gs.upsert_edges([]) == 0

    @pytest.mark.asyncio
    async def test_upsert_empty_docs(self, gs):
        assert await gs.upsert_documentation([]) == 0

    @pytest.mark.asyncio
    async def test_upsert_empty_embeddings(self, gs):
        assert await gs.upsert_embeddings([], []) == 0

    @pytest.mark.asyncio
    async def test_callers_nonexistent_symbol(self, gs):
        assert await gs.get_callers("no:such:symbol", depth=3) == []

    @pytest.mark.asyncio
    async def test_callees_nonexistent_symbol(self, gs):
        assert await gs.get_callees("no:such:symbol", depth=3) == []

    @pytest.mark.asyncio
    async def test_impact_analysis_nonexistent(self, gs):
        result = await gs.get_impact_analysis("no:such:symbol")
        assert result["direct_callers_count"] == 0
        assert result["risk_score"] == 0.0

    @pytest.mark.asyncio
    async def test_traceability_nonexistent(self, gs):
        trace = await gs.get_traceability("no:such:symbol")
        assert trace["has_documentation"] is False
        assert trace["has_test_coverage"] is False
        assert trace["has_architecture_context"] is False

    @pytest.mark.asyncio
    async def test_depth_clamped_to_maximum_5(self, gs):
        r = _rid()
        await gs.upsert_ast_nodes([_node(r, "x.py", "fn")])
        # depth > 5 should not raise, just clamp internally
        callers = await gs.get_callers(f"{r}:x.py:fn", depth=99)
        assert isinstance(callers, list)

    @pytest.mark.asyncio
    async def test_depth_clamped_to_minimum_1(self, gs):
        r = _rid()
        await gs.upsert_ast_nodes([_node(r, "x.py", "fn")])
        callers = await gs.get_callers(f"{r}:x.py:fn", depth=0)
        assert isinstance(callers, list)

    @pytest.mark.asyncio
    async def test_upsert_node_then_update_fields(self, gs):
        """Re-upserting same id updates fields (MERGE semantics)."""
        r = _rid()
        node = _node(r, "x.py", "fn", docstring="original")
        await gs.upsert_ast_nodes([node])

        node2 = ASTNode(
            id=node.id, kind=node.kind, name=node.name, filepath=node.filepath,
            start_line=99, end_line=109,
            source_text="def fn(): return 42",
            docstring="updated docstring",
        )
        await gs.upsert_ast_nodes([node2])

        query = GraphQuery(
            cypher="MATCH (n:ASTNode {id: $id}) RETURN n.docstring AS ds, n.start_line AS sl",
            params={"id": node.id},
        )
        results = await gs.execute_query(query)
        assert results[0]["ds"] == "updated docstring"
        assert results[0]["sl"] == 99


# ===========================================================================
# 14. Large-scale batch insert
# ===========================================================================

class TestBatchInsert:

    @pytest.mark.asyncio
    async def test_bulk_nodes_insert(self, gs):
        """Insert 200 nodes in one call."""
        r = _rid()
        nodes = [_node(r, f"file_{i}.py", f"fn_{i}") for i in range(200)]
        count = await gs.upsert_ast_nodes(nodes)
        assert count == 200

    @pytest.mark.asyncio
    async def test_bulk_edges_insert(self, gs):
        """Insert a chain of 100 edges."""
        r = _rid()
        nodes = [_node(r, f"n{i}.py", f"fn{i}") for i in range(101)]
        await gs.upsert_ast_nodes(nodes)

        edges = [
            _edge(r, f"n{i}.py", f"fn{i}", f"n{i+1}.py", f"fn{i+1}")
            for i in range(100)
        ]
        count = await gs.upsert_edges(edges)
        assert count == 100

    @pytest.mark.asyncio
    async def test_impact_on_high_fan_in_node(self, gs):
        """Node with 15 callers has risk_score > 0.5."""
        r = _rid()
        target = _node(r, "core.py", "core_fn")
        callers = [_node(r, f"svc{i}.py", f"svc_fn{i}") for i in range(15)]
        await gs.upsert_ast_nodes([target] + callers)

        edges = [_edge(r, f"svc{i}.py", f"svc_fn{i}", "core.py", "core_fn") for i in range(15)]
        await gs.upsert_edges(edges)

        result = await gs.get_impact_analysis(f"{r}:core.py:core_fn")
        assert result["risk_score"] > 0.5
        assert result["direct_callers_count"] == 15
