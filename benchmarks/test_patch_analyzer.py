"""Test patch analyzer for the Xanther Context Engine.

Parses SWE-bench test patches to extract signals about which production
code the tests exercise, guiding context retrieval.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from xce.models import TestPatchSignal, TraversalState

logger = logging.getLogger(__name__)

# Test framework methods to exclude from symbol extraction
_TEST_FRAMEWORK_METHODS = frozenset({
    "assert", "assertEqual", "assertNotEqual", "assertTrue", "assertFalse",
    "assertIs", "assertIsNot", "assertIsNone", "assertIsNotNone",
    "assertIn", "assertNotIn", "assertIsInstance", "assertNotIsInstance",
    "assertRaises", "assertRaisesRegex", "assertWarns", "assertWarnsRegex",
    "assertLogs", "assertAlmostEqual", "assertNotAlmostEqual",
    "assertGreater", "assertGreaterEqual", "assertLess", "assertLessEqual",
    "assertRegex", "assertNotRegex", "assertCountEqual",
    "assertMultiLineEqual", "assertSequenceEqual", "assertListEqual",
    "assertTupleEqual", "assertSetEqual", "assertDictEqual",
    "setUp", "tearDown", "setUpClass", "tearDownClass",
    "setUpModule", "tearDownModule",
    "fail", "skipTest", "subTest",
    "print", "len", "str", "int", "float", "list", "dict", "set", "tuple",
    "range", "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "isinstance", "issubclass", "hasattr", "getattr", "setattr", "type",
    "super", "self",
})


class TestPatchAnalyzer:
    """Analyze test patches to extract production code signals."""

    # ------------------------------------------------------------------
    # 14.2  analyze — parse unified diff
    # ------------------------------------------------------------------

    def analyze(self, test_patch: str, repo_id: str = "") -> TestPatchSignal:
        """Parse a test patch diff and extract signals.

        Returns an empty TestPatchSignal for malformed/empty patches.
        """
        if not test_patch or not test_patch.strip():
            return TestPatchSignal()

        try:
            added_lines = self._extract_added_lines(test_patch)
        except Exception as exc:
            logger.warning("Failed to parse test patch: %s", exc)
            return TestPatchSignal()

        if not added_lines:
            return TestPatchSignal()

        test_source = "\n".join(added_lines)

        imports = self._extract_imports(test_source)
        tested_files = self._imports_to_files(imports)
        symbols = self._extract_tested_symbols(test_source)
        assertions = self._extract_assertions(test_source)
        edge_cases = self._extract_edge_cases(test_source)

        # Compute priority scores
        import_symbols = set()
        for imp in imports:
            import_symbols.update(imp.get("names", []))

        priority_score: dict[str, float] = {}
        for sym in symbols:
            if sym in import_symbols:
                priority_score[sym] = 1.0
            else:
                priority_score[sym] = 0.5

        return TestPatchSignal(
            tested_files=tested_files,
            tested_symbols=symbols,
            test_assertions=assertions,
            edge_cases=edge_cases,
            priority_score=priority_score,
        )

    # ------------------------------------------------------------------
    # Diff parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_added_lines(patch: str) -> list[str]:
        """Extract added lines (starting with +) from a unified diff."""
        added: list[str] = []
        for line in patch.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])  # strip the leading +
        return added

    # ------------------------------------------------------------------
    # 14.3  _extract_imports
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_imports(test_source: str) -> list[dict[str, Any]]:
        """Extract import statements from test code."""
        imports: list[dict[str, Any]] = []

        # from X import Y, Z
        from_pattern = re.compile(r"from\s+([\w.]+)\s+import\s+([\w, *]+)")
        for match in from_pattern.finditer(test_source):
            module = match.group(1)
            names = [n.strip() for n in match.group(2).split(",") if n.strip() and n.strip() != "*"]
            imports.append({"module": module, "names": names})

        # import X
        import_pattern = re.compile(r"^import\s+([\w.]+)", re.MULTILINE)
        for match in import_pattern.finditer(test_source):
            module = match.group(1)
            imports.append({"module": module, "names": [module.split(".")[-1]]})

        return imports

    @staticmethod
    def _imports_to_files(imports: list[dict[str, Any]]) -> list[str]:
        """Convert import module paths to file paths."""
        files: list[str] = []
        seen: set[str] = set()
        for imp in imports:
            module = imp["module"]
            filepath = module.replace(".", "/") + ".py"
            if filepath not in seen:
                seen.add(filepath)
                files.append(filepath)
        return files

    # ------------------------------------------------------------------
    # 14.4  _extract_tested_symbols
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_tested_symbols(test_source: str) -> list[str]:
        """Extract function/class names called or instantiated in test bodies.

        Excludes test framework methods.
        """
        # Match function calls: name(
        call_pattern = re.compile(r"(?:self\.)?(\w+)\s*\(")
        symbols: set[str] = set()

        for match in call_pattern.finditer(test_source):
            name = match.group(1)
            if name not in _TEST_FRAMEWORK_METHODS and not name.startswith("test_"):
                symbols.add(name)

        # Match class instantiation: ClassName(
        class_pattern = re.compile(r"\b([A-Z]\w+)\s*\(")
        for match in class_pattern.finditer(test_source):
            name = match.group(1)
            if name not in _TEST_FRAMEWORK_METHODS:
                symbols.add(name)

        return sorted(symbols)

    # ------------------------------------------------------------------
    # 14.5  _extract_assertions
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_assertions(test_source: str) -> list[str]:
        """Extract assert statements from test code."""
        assertions: list[str] = []

        # self.assertXxx(...)
        pattern = re.compile(r"(self\.assert\w+\([^)]*\))")
        for match in pattern.finditer(test_source):
            assertions.append(match.group(1))

        # bare assert statements
        bare_pattern = re.compile(r"^(\s*assert\s+.+)$", re.MULTILINE)
        for match in bare_pattern.finditer(test_source):
            assertions.append(match.group(1).strip())

        return assertions

    # ------------------------------------------------------------------
    # 14.6  _extract_edge_cases
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_edge_cases(test_source: str) -> list[str]:
        """Detect edge case patterns in test code."""
        edge_cases: list[str] = []
        patterns = {
            "None/null check": r"(?:None|null|nil)\b",
            "Empty collection": r"(?:\[\]|\(\)|{}|\.empty|len\([^)]*\)\s*==\s*0)",
            "Boundary value": r"(?:\b0\b|\b1\b|\b-1\b|MAX|MIN|boundary)",
            "Exception handling": r"(?:assertRaises|with\s+self\.assertRaises|pytest\.raises)",
        }
        for case_name, pattern in patterns.items():
            if re.search(pattern, test_source):
                edge_cases.append(case_name)
        return edge_cases

    # ------------------------------------------------------------------
    # 14.7  boost_traversal_priority
    # ------------------------------------------------------------------

    @staticmethod
    def boost_traversal_priority(
        signal: TestPatchSignal,
        traversal_state: TraversalState,
    ) -> TraversalState:
        """Inject test patch signals as high-priority seeds into traversal state.

        Directly imported symbols get priority 1.0, indirectly referenced get 0.5.
        """
        if not signal.tested_symbols:
            return traversal_state

        boosted_context: list[dict[str, Any]] = []
        for symbol in signal.tested_symbols:
            priority = signal.priority_score.get(symbol, 0.5)
            boosted_context.append({
                "type": "test_patch_signal",
                "node_id": symbol,
                "priority": priority,
                "data": {"name": symbol, "source": "test_patch"},
            })

        # Prepend boosted context so it's visited first
        new_state = dict(traversal_state)
        new_state["collected_context"] = boosted_context + list(traversal_state["collected_context"])
        return TraversalState(**new_state)  # type: ignore[typeddict-item]
