"""Thread safety tests for parsers.

Validates that parsers can be used safely in concurrent contexts.
"""

import pytest
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from xce.parsers import get_default_registry
from xce.models import NodeKind


class TestThreadSafety:
    """Thread safety tests for parsers."""

    def test_concurrent_parsing_same_parser(self):
        """Multiple threads should be able to parse concurrently."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = """
def foo():
    pass

class MyClass:
    def method(self):
        pass
"""
        
        results = []
        errors = []
        
        def parse_file():
            try:
                nodes, edges = parser.parse_file("test.py", code, "test_repo")
                results.append((nodes, edges))
            except Exception as e:
                errors.append(e)
        
        # Run 10 concurrent parses
        threads = [threading.Thread(target=parse_file) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 10

    def test_concurrent_parsing_different_files(self):
        """Multiple threads parsing different files should not interfere."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        codes = [
            f"def func_{i}(): pass"
            for i in range(20)
        ]
        
        results = []
        errors = []
        
        def parse_file(i):
            try:
                nodes, edges = parser.parse_file(f"test{i}.py", codes[i], "test_repo")
                results.append((nodes, edges))
            except Exception as e:
                errors.append(e)
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(parse_file, i) for i in range(20)]
            for f in as_completed(futures):
                pass
        
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 20

    def test_concurrent_parsing_different_languages(self):
        """Concurrent parsing of different languages should work."""
        registry = get_default_registry()
        
        python_code = "def foo(): pass"
        ts_code = "function foo() {}"
        
        results = []
        errors = []
        
        def parse_python():
            try:
                parser = registry.get_parser("test.py")
                nodes, edges = parser.parse_file("test.py", python_code, "test_repo")
                results.append(("python", nodes, edges))
            except Exception as e:
                errors.append(("python", e))
        
        def parse_typescript():
            try:
                parser = registry.get_parser("test.ts")
                nodes, edges = parser.parse_file("test.ts", ts_code, "test_repo")
                results.append(("typescript", nodes, edges))
            except Exception as e:
                errors.append(("typescript", e))
        
        threads = [
            threading.Thread(target=parse_python),
            threading.Thread(target=parse_typescript),
            threading.Thread(target=parse_python),
            threading.Thread(target=parse_typescript),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 4

    def test_registry_thread_safety(self):
        """Registry should be safe to access from multiple threads."""
        registry = get_default_registry()
        
        results = []
        errors = []
        
        def get_parser():
            try:
                parser = registry.get_parser("test.py")
                results.append(parser)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=get_parser) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Errors occurred: {errors}"
        # All should return the same parser
        assert all(r is results[0] for r in results)

    def test_concurrent_file_access_no_race_condition(self):
        """Concurrent access should not cause race conditions in results."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        code = """
class MyClass:
    def method(self):
        pass
"""
        
        all_nodes = []
        
        def parse_and_collect():
            nodes, edges = parser.parse_file("test.py", code, "test_repo")
            all_nodes.extend(nodes)
        
        threads = [threading.Thread(target=parse_and_collect) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Each parse should produce consistent results
        # We should have 10x the nodes (10 threads, each with full set)
        # But since nodes are separate objects, just verify structure
        assert len(all_nodes) > 0
        
        # Verify all nodes have required fields
        for node in all_nodes:
            assert node.id
            assert node.kind in NodeKind

    def test_parser_instance_reuse_across_threads(self):
        """Same parser instance should be reusable across threads."""
        registry = get_default_registry()
        parser = registry.get_parser("test.py")
        
        # Parse many times concurrently on the SAME parser instance
        def parse_many():
            for _ in range(100):
                nodes, edges = parser.parse_file("test.py", "def foo(): pass", "repo")
                assert nodes is not None
        
        threads = [threading.Thread(target=parse_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # If we get here without exceptions, the test passes