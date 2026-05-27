# Implementation Plan: Multi-Language Parser Overhaul

## Overview

This plan transforms XCE's parser system from two ad-hoc implementations into a pluggable, registry-based architecture supporting 11 languages. Tasks are ordered by dependency: foundation (interfaces, data models, registry), then refactored parsers (Python, TypeScript), then new language parsers, then tests, and finally open source preparation files.

## Tasks

- [x] 1. Create parser package foundation
  - [x] 1.1 Create `xce/parsers/__init__.py` with package exports
    - Export `BaseParser`, `TreeSitterBaseParser`, `ParserRegistry`, `get_default_registry`, `NodeTypeMapping`
    - _Requirements: 1.1, 1.2, 1.3_
  - [x] 1.2 Create `xce/parsers/base.py` with the `BaseParser` abstract base class
    - Define abstract methods: `parse_file(filepath, source, repo_id) -> tuple[list[ASTNode], list[ASTEdge]]`, `supported_extensions() -> list[str]`, `language_name() -> str`
    - _Requirements: 1.1, 1.2, 1.3_
  - [x] 1.3 Create `xce/parsers/registry.py` with the `ParserRegistry` class
    - Implement `register(parser)` with duplicate-extension detection raising `ValueError`
    - Implement `freeze()` to make registry immutable
    - Implement `get_parser(filepath)` returning parser or `None` for unknown extensions
    - Implement `supported_extensions` and `languages` properties
    - _Requirements: 1.4, 1.5, 1.6, 1.7, 8.3, 10.1_
  - [x] 1.4 Create `xce/parsers/tree_sitter_base.py` with `NodeTypeMapping` dataclass and `TreeSitterBaseParser` class
    - Define frozen `NodeTypeMapping` dataclass with all fields from design (module_types, class_types, function_types, import_types, variable_types, call_types, name_field, parameters_field, body_field, inheritance_types, decorator_types, method_parent_types, comment_types, max_file_size)
    - Implement `TreeSitterBaseParser` with: fresh `tree_sitter.Parser` per call (thread-safe), tree walking logic, module node creation, node extraction using mapping, edge creation for contains/calls/imports/inherits/decorates
    - Enforce 1MB file size limit (return empty lists and log warning)
    - Catch all exceptions in `parse_file` and return partial/empty results
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 7.1, 7.3, 8.1, 8.2_

- [x] 2. Checkpoint - Verify foundation compiles
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Refactor existing Python parser
  - [x] 3.1 Create `xce/parsers/python_parser.py` implementing `BaseParser`
    - Move `_FileVisitor` logic from `xce/parser.py` into `PythonParser.parse_file(filepath, source, repo_id)`
    - Register extensions `.py` and `.pyi`
    - Preserve identical output behavior (same ASTNode/ASTEdge instances for same input)
    - Handle syntax errors gracefully (return empty lists, log warning)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - [x] 3.2 Update `xce/parser.py` to be a backward-compatible shim
    - Import `PythonParser` from new location
    - Keep `ASTParser` class with same public API, delegating to `PythonParser` internally
    - Preserve `parse_repository`, `resolve_cross_file_imports`, and `_discover_py_files` functions
    - _Requirements: 3.3_

- [x] 4. Refactor existing TypeScript parser
  - [x] 4.1 Create `xce/parsers/typescript_parser.py` implementing `TreeSitterBaseParser`
    - Provide `NodeTypeMapping` for TypeScript/JavaScript (class_declaration, function_declaration, arrow_function, method_definition, import_statement, lexical_declaration, extends_clause)
    - Register extensions `.ts`, `.tsx`, `.js`, `.jsx`
    - Override `parse_file` to select correct tree-sitter language (TypeScript vs TSX vs JavaScript) based on file extension
    - Handle syntax errors gracefully
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 5. Add new language parsers (tree-sitter based)
  - [x] 5.1 Create `xce/parsers/go_parser.py`
    - Provide `NodeTypeMapping`: module_types=(`package_clause`), class_types=(`type_declaration`), function_types=(`function_declaration`, `method_declaration`), import_types=(`import_declaration`), variable_types=(`var_declaration`, `const_declaration`)
    - Register extension `.go`
    - _Requirements: 5.1, 5.10, 5.11_
  - [x] 5.2 Create `xce/parsers/rust_parser.py`
    - Provide `NodeTypeMapping`: class_types=(`struct_item`, `enum_item`, `trait_item`, `impl_item`), function_types=(`function_item`), import_types=(`use_declaration`)
    - Register extension `.rs`
    - _Requirements: 5.2, 5.10, 5.11_
  - [x] 5.3 Create `xce/parsers/java_parser.py`
    - Provide `NodeTypeMapping`: class_types=(`class_declaration`, `interface_declaration`), function_types=(`method_declaration`, `constructor_declaration`), import_types=(`import_declaration`)
    - Register extension `.java`
    - _Requirements: 5.3, 5.10, 5.11_
  - [x] 5.4 Create `xce/parsers/csharp_parser.py`
    - Provide `NodeTypeMapping`: class_types=(`class_declaration`, `interface_declaration`, `struct_declaration`), function_types=(`method_declaration`, `constructor_declaration`), import_types=(`using_directive`)
    - Register extension `.cs`
    - _Requirements: 5.4, 5.10, 5.11_
  - [x] 5.5 Create `xce/parsers/ruby_parser.py`
    - Provide `NodeTypeMapping`: class_types=(`class`, `module`), function_types=(`method`, `singleton_method`), import_types=(`call` for require/require_relative)
    - Register extension `.rb`
    - _Requirements: 5.5, 5.10, 5.11_
  - [x] 5.6 Create `xce/parsers/php_parser.py`
    - Provide `NodeTypeMapping`: class_types=(`class_declaration`, `interface_declaration`, `trait_declaration`), function_types=(`function_definition`, `method_declaration`), import_types=(`namespace_use_declaration`)
    - Register extension `.php`
    - _Requirements: 5.6, 5.10, 5.11_
  - [x] 5.7 Create `xce/parsers/kotlin_parser.py`
    - Provide `NodeTypeMapping`: class_types=(`class_declaration`, `interface_declaration`, `object_declaration`), function_types=(`function_declaration`), import_types=(`import_header`)
    - Register extensions `.kt`, `.kts`
    - _Requirements: 5.7, 5.10, 5.11_
  - [x] 5.8 Create `xce/parsers/swift_parser.py`
    - Provide `NodeTypeMapping`: class_types=(`class_declaration`, `struct_declaration`, `protocol_declaration`), function_types=(`function_declaration`), import_types=(`import_declaration`)
    - Register extension `.swift`
    - _Requirements: 5.8, 5.10, 5.11_
  - [x] 5.9 Create `xce/parsers/cpp_parser.py`
    - Provide `NodeTypeMapping`: class_types=(`class_specifier`, `struct_specifier`), function_types=(`function_definition`, `declaration`), import_types=(`preproc_include`)
    - Register extensions `.c`, `.cpp`, `.cc`, `.cxx`, `.h`, `.hpp`
    - _Requirements: 5.9, 5.10, 5.11_

- [x] 6. Wire registry and integrate with indexer
  - [x] 6.1 Implement `get_default_registry()` in `xce/parsers/__init__.py`
    - Register PythonParser directly (always available)
    - Use `_try_register` pattern for all tree-sitter parsers (graceful skip on grammar load failure)
    - Freeze registry after all registrations
    - _Requirements: 7.4, 10.1, 10.2_
  - [x] 6.2 Update `xce/indexer.py` to use `ParserRegistry`
    - Replace direct `ASTParser` usage with `get_default_registry().get_parser(filepath)` calls
    - Skip files with no registered parser (return no error)
    - Support all registered extensions for file discovery
    - _Requirements: 10.1, 10.3_

- [x] 7. Update dependencies in `pyproject.toml`
  - Add tree-sitter grammar packages: `tree-sitter-typescript>=0.23`, `tree-sitter-javascript>=0.23`, `tree-sitter-go>=0.23`, `tree-sitter-rust>=0.23`, `tree-sitter-java>=0.23`, `tree-sitter-c-sharp>=0.23`, `tree-sitter-ruby>=0.23`, `tree-sitter-php>=0.23`, `tree-sitter-kotlin>=0.23`, `tree-sitter-swift>=0.23`, `tree-sitter-c>=0.23`, `tree-sitter-cpp>=0.23`
  - Update license field from `"MIT"` to `"AGPL-3.0-or-later"`
  - _Requirements: 9.6, 9.7_

- [x] 8. Checkpoint - Verify all parsers load and registry works
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Create test fixtures and unit tests
  - [x] 9.1 Create `tests/parsers/` directory with `__init__.py` and `conftest.py`
    - Set up shared fixtures: sample source strings, registry instance, repo_id generator
    - _Requirements: 6.1, 6.2, 6.3_
  - [x] 9.2 Create `tests/parsers/fixtures/` with sample source files
    - One representative file per language: `sample.py`, `sample.ts`, `sample.go`, `sample.rs`, `sample.java`, `sample.cs`, `sample.rb`, `sample.php`, `sample.kt`, `sample.swift`, `sample.cpp`, `sample.h`
    - Each file should contain at least: a module/package declaration, a class, a function, an import, and a nested method
    - _Requirements: 5.1–5.9_
  - [x] 9.3 Create `tests/parsers/test_registry.py` with registry unit tests
    - Test: register parser, get_parser returns correct parser for registered extension
    - Test: duplicate extension raises ValueError
    - Test: unknown extension returns None
    - Test: freeze prevents further registration
    - Test: all expected extensions are registered in default registry
    - _Requirements: 1.4, 1.5, 1.6, 1.7, 10.2_
  - [x] 9.4 Create `tests/parsers/test_python_parser.py` with backward compatibility tests
    - Test: PythonParser produces same output as original ASTParser for sample files
    - Test: syntax error returns empty lists
    - Test: output contains MODULE node, CONTAINS edges, CALLS edges
    - _Requirements: 3.3, 3.4, 6.3_
  - [x] 9.5 Create `tests/parsers/test_typescript_parser.py`
    - Test: parses .ts file extracting classes, functions, imports
    - Test: parses .tsx file correctly
    - Test: parses .js file correctly
    - Test: syntax error returns partial results
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
  - [x] 9.6 Create `tests/parsers/test_language_parsers.py` for all new language parsers
    - Parametrized tests across Go, Rust, Java, C#, Ruby, PHP, Kotlin, Swift, C/C++
    - Each parser: produces MODULE node, extracts classes/functions/imports, produces valid ASTNode IDs
    - _Requirements: 5.1–5.9, 6.1, 6.2, 6.3_

- [x] 10. Write property-based tests (Hypothesis)
  - [x] 10.1 Create `tests/parsers/test_registry_properties.py`
    - **Property 1: Registry extension round-trip** — For any set of parsers with non-overlapping extensions, get_parser returns the correct parser for each registered extension
    - **Property 2: Registry duplicate detection** — For any two parsers sharing an extension, registration raises ValueError
    - **Property 3: Registry returns None for unknown extensions** — For any filepath with unregistered extension, get_parser returns None
    - **Validates: Requirements 1.4, 1.5, 1.6, 1.7, 10.1, 10.3**
  - [x] 10.2 Create `tests/parsers/test_output_properties.py`
    - **Property 4: ASTNode ID format invariant** — For any parsed file, all node IDs match `{repo_id}:{filepath}:{kind}:{name}` pattern
    - **Property 5: Output type validity** — For any parsed file, all node kinds are valid NodeKind values and all edge relations are in the allowed set
    - **Property 6: Module node invariant** — For any non-empty source, output contains at least one MODULE node
    - **Validates: Requirements 6.1, 6.2, 6.3, 2.5, 2.6**
  - [x] 10.3 Create `tests/parsers/test_python_parser_properties.py`
    - **Property 7: Python parser backward compatibility** — For any valid Python source, PythonParser produces identical output to original ASTParser
    - **Validates: Requirements 3.3**
  - [x] 10.4 Create `tests/parsers/test_error_handling_properties.py`
    - **Property 8: Graceful error handling** — For any byte string (including malformed source), parse_file returns a tuple without raising
    - **Property 9: File size limit enforcement** — For any source exceeding 1MB UTF-8, TreeSitterBaseParser returns ([], [])
    - **Validates: Requirements 3.4, 4.4, 7.1, 7.3**
  - [x] 10.5 Create `tests/parsers/test_thread_safety.py`
    - **Property 10: Concurrent parsing determinism** — For any source file and parser, parsing N times concurrently produces identical results to N sequential parses
    - **Validates: Requirements 8.1, 8.2**

- [x] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Open source repository preparation
  - [x] 12.1 Create `LICENSE` file at repository root
    - Full AGPL-3.0 license text
    - _Requirements: 9.1_
  - [x] 12.2 Create `COMMERCIAL_LICENSE.md` at repository root
    - Explain dual licensing model: AGPL-3.0 for open source use, commercial license available for proprietary use
    - _Requirements: 9.4_
  - [x] 12.3 Create `CONTRIBUTING.md` at repository root
    - Include: PR process, code style (ruff config), testing requirements (pytest + hypothesis), commit message format, how to add a new language parser
    - _Requirements: 9.3_
  - [x] 12.4 Create `.env.example` at repository root
    - List all required environment variables with placeholder values: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, OPENAI_API_KEY, OPENAI_MODEL, HOST, PORT, LOG_LEVEL
    - _Requirements: 9.2_
  - [x] 12.5 Audit `xce/` package for hardcoded secrets
    - Scan all Python files in `xce/` for hardcoded API keys, tokens, or secrets
    - Replace any found with environment variable references
    - _Requirements: 9.5_

- [x] 13. Final checkpoint - Ensure all tests pass and project builds
  - Ensure all tests pass, ask the user if questions arise.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "name": "Foundation",
      "tasks": ["1"],
      "description": "Create parser package structure, BaseParser ABC, registry, and TreeSitterBaseParser"
    },
    {
      "name": "Parser Refactoring",
      "tasks": ["2", "3", "4"],
      "description": "Verify foundation, refactor Python and TypeScript parsers into new architecture"
    },
    {
      "name": "New Language Parsers",
      "tasks": ["5", "6", "7"],
      "description": "Add 9 new language parsers, wire registry to indexer, update dependencies"
    },
    {
      "name": "Testing",
      "tasks": ["8", "9", "10", "11"],
      "description": "Verify parsers load, create test fixtures, unit tests, and property-based tests"
    },
    {
      "name": "Open Source Preparation",
      "tasks": ["12", "13"],
      "description": "Add license, contributing docs, env example, audit for secrets"
    }
  ]
}
```

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The Python parser keeps using stdlib `ast` (not tree-sitter) for superior semantic accuracy
- All tree-sitter parsers share the same `TreeSitterBaseParser` logic — each language parser is ~50 lines of config
- Property tests use `hypothesis` (already in dev dependencies) with `@settings(max_examples=100)`
- The existing `xce/parser.py` becomes a backward-compatible shim to avoid breaking existing callers
