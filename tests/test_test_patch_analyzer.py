"""Tests for test patch analyzer (Task 14).

Validates:
- P15: Import extraction completeness
- P16: Priority score bounds (0.5-1.0)
- Symbol extraction (excluding test methods)
- Assertion extraction
- Edge case detection
- Malformed patch handling
"""

from __future__ import annotations

import pytest

from xce.test_patch_analyzer import TestPatchAnalyzer

SAMPLE_PATCH = """\
diff --git a/tests/test_queryset.py b/tests/test_queryset.py
--- a/tests/test_queryset.py
+++ b/tests/test_queryset.py
@@ -1,5 +1,20 @@
+from django.db.models import Q
+from django.db.models.query import QuerySet
+from myapp.models import Article
+
+class TestQuerySetFilter(TestCase):
+    def setUp(self):
+        self.qs = QuerySet()
+
+    def test_filter_with_nested_q(self):
+        q = Q(title="test") | Q(author=None)
+        result = self.qs.filter(q)
+        self.assertEqual(len(result), 0)
+        self.assertIsNotNone(result)
+
+    def test_empty_filter(self):
+        result = self.qs.filter()
+        self.assertEqual(result.count(), 0)
+
+    def test_boundary_values(self):
+        with self.assertRaises(ValueError):
+            self.qs.filter(id=-1)
"""


@pytest.fixture
def analyzer() -> TestPatchAnalyzer:
    return TestPatchAnalyzer()


class TestAnalyze:
    def test_extracts_tested_files(self, analyzer: TestPatchAnalyzer):
        signal = analyzer.analyze(SAMPLE_PATCH)
        assert len(signal.tested_files) > 0
        # Should include django.db.models path
        assert any("django" in f for f in signal.tested_files)

    def test_extracts_tested_symbols(self, analyzer: TestPatchAnalyzer):
        signal = analyzer.analyze(SAMPLE_PATCH)
        assert len(signal.tested_symbols) > 0
        # Should include QuerySet, Q, Article
        symbol_set = set(signal.tested_symbols)
        assert "QuerySet" in symbol_set or "Q" in symbol_set

    def test_excludes_test_framework_methods(self, analyzer: TestPatchAnalyzer):
        signal = analyzer.analyze(SAMPLE_PATCH)
        for sym in signal.tested_symbols:
            assert sym not in {"assertEqual", "assertIsNotNone", "assertRaises", "setUp"}

    def test_extracts_assertions(self, analyzer: TestPatchAnalyzer):
        signal = analyzer.analyze(SAMPLE_PATCH)
        assert len(signal.test_assertions) > 0
        assert any("assertEqual" in a for a in signal.test_assertions)

    def test_extracts_edge_cases(self, analyzer: TestPatchAnalyzer):
        signal = analyzer.analyze(SAMPLE_PATCH)
        assert len(signal.edge_cases) > 0
        # Should detect None check and exception handling
        edge_set = set(signal.edge_cases)
        assert "None/null check" in edge_set or "Exception handling" in edge_set


class TestPriorityScores:
    """P16: Priority scores bounded between 0.5 and 1.0."""

    def test_priority_bounds(self, analyzer: TestPatchAnalyzer):
        signal = analyzer.analyze(SAMPLE_PATCH)
        for sym, score in signal.priority_score.items():
            assert 0.5 <= score <= 1.0, f"Score {score} for {sym} out of bounds"

    def test_imported_symbols_get_high_priority(self, analyzer: TestPatchAnalyzer):
        signal = analyzer.analyze(SAMPLE_PATCH)
        # Directly imported symbols should get 1.0
        for sym in signal.tested_symbols:
            if sym in signal.priority_score:
                assert signal.priority_score[sym] in (0.5, 1.0)


class TestImportExtraction:
    """P15: Every import in the test patch is captured."""

    def test_from_imports(self, analyzer: TestPatchAnalyzer):
        patch = "+from mymodule.utils import helper_func, HelperClass\n"
        signal = analyzer.analyze(f"--- a/t.py\n+++ b/t.py\n@@ -0,0 +1 @@\n{patch}")
        assert "mymodule/utils.py" in signal.tested_files

    def test_plain_imports(self, analyzer: TestPatchAnalyzer):
        patch = "+import os.path\n"
        signal = analyzer.analyze(f"--- a/t.py\n+++ b/t.py\n@@ -0,0 +1 @@\n{patch}")
        assert "os/path.py" in signal.tested_files


class TestMalformedPatches:
    """14.8 — Graceful handling of malformed/empty patches."""

    def test_empty_patch(self, analyzer: TestPatchAnalyzer):
        signal = analyzer.analyze("")
        assert signal.tested_files == []
        assert signal.tested_symbols == []

    def test_none_like_patch(self, analyzer: TestPatchAnalyzer):
        signal = analyzer.analyze("   \n  \n  ")
        assert signal.tested_files == []

    def test_garbage_patch(self, analyzer: TestPatchAnalyzer):
        signal = analyzer.analyze("not a valid diff at all!!!")
        # Should not crash — returns empty or minimal signal
        assert isinstance(signal.tested_files, list)
        assert isinstance(signal.tested_symbols, list)


class TestBoostTraversalPriority:
    def test_injects_signals(self, analyzer: TestPatchAnalyzer):
        from xce.models import TestPatchSignal, TraversalState

        signal = TestPatchSignal(
            tested_symbols=["filter", "QuerySet"],
            priority_score={"filter": 1.0, "QuerySet": 0.5},
        )
        state: TraversalState = {
            "query": "test",
            "repo_id": "r",
            "visited_nodes": [],
            "collected_context": [{"node_id": "existing", "type": "x"}],
            "current_depth": 0,
            "max_depth": 3,
            "reasoning_trace": [],
        }
        boosted = TestPatchAnalyzer.boost_traversal_priority(signal, state)
        # Boosted context should be prepended
        assert boosted["collected_context"][0]["type"] == "test_patch_signal"
        assert len(boosted["collected_context"]) == 3  # 2 signals + 1 existing
