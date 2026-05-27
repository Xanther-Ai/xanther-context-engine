# Requirements Document

## Introduction

This feature overhauls the Xanther Context Engine's parser system from a two-language ad-hoc implementation into a pluggable, registry-based architecture supporting 19+ programming languages via tree-sitter. It also prepares the repository for open source release under AGPL-3.0, including license files, secret removal, dependency updates, and contributor documentation.

## Glossary

- **Parser_Registry**: The module responsible for mapping file extensions to their corresponding parser implementations and providing auto-detection of language from file paths
- **BaseParser**: The abstract interface that all language-specific parsers must implement, defining the contract for file parsing
- **TreeSitterBaseParser**: A generic tree-sitter-based parser class that provides shared logic for tree walking, node extraction, and edge creation — language-specific parsers subclass it with node-type mappings
- **ASTNode**: A dataclass representing a single structural element extracted from source code (module, class, function, method, import, variable, decorator, argument)
- **ASTEdge**: A dataclass representing a directed relationship between two ASTNodes (contains, calls, imports, inherits, decorates)
- **NodeKind**: An enum defining the types of structural elements that parsers extract
- **Language_Parser**: A concrete parser implementation for a specific programming language that produces ASTNode and ASTEdge instances
- **Node_Type_Mapping**: A configuration object that maps tree-sitter grammar node types to XCE NodeKind values for a specific language

## Requirements

### Requirement 1: Pluggable Parser Architecture

**User Story:** As a developer extending XCE, I want a well-defined parser interface and registry system, so that I can add support for new languages without modifying existing code.

#### Acceptance Criteria

1. THE BaseParser SHALL define an abstract method `parse_file` that accepts a filepath string, source string, and repo_id string and returns a tuple of `list[ASTNode]` and `list[ASTEdge]`
2. THE BaseParser SHALL define an abstract method `supported_extensions` that returns a `list[str]` of file extensions the parser handles
3. THE BaseParser SHALL define an abstract method `language_name` that returns a string identifying the language
4. THE Parser_Registry SHALL maintain a mapping from file extensions to parser instances
5. WHEN a file extension is registered by multiple parsers, THEN THE Parser_Registry SHALL raise a configuration error at registration time
6. WHEN a file path is provided to the Parser_Registry, THE Parser_Registry SHALL return the appropriate parser based on the file extension
7. WHEN a file has an unrecognized extension, THE Parser_Registry SHALL return None to indicate no parser is available

### Requirement 2: Tree-Sitter Generic Base Parser

**User Story:** As a developer adding a new language, I want a generic tree-sitter base class that handles common parsing logic, so that I only need to provide language-specific node-type mappings (~50 lines of configuration).

#### Acceptance Criteria

1. THE TreeSitterBaseParser SHALL load the tree-sitter grammar for the configured language
2. THE TreeSitterBaseParser SHALL walk the parsed syntax tree and extract nodes matching the configured node-type mappings
3. THE TreeSitterBaseParser SHALL extract modules, classes, functions, methods, imports, inheritance relationships, call edges, and contains edges from any supported language
4. WHEN a Language_Parser subclasses TreeSitterBaseParser, THE Language_Parser SHALL only need to provide a Node_Type_Mapping configuration specifying which tree-sitter node types correspond to functions, classes, imports, and calls
5. THE TreeSitterBaseParser SHALL produce ASTNode instances with correctly populated id, kind, name, filepath, start_line, end_line, source_text, and signature fields
6. THE TreeSitterBaseParser SHALL produce ASTEdge instances with relation values from the set: "contains", "calls", "imports", "inherits", "decorates"

### Requirement 3: Python Parser Refactoring

**User Story:** As a maintainer, I want the existing Python parser refactored into the new architecture, so that it conforms to the BaseParser interface while preserving its current behavior.

#### Acceptance Criteria

1. THE Python_Parser SHALL implement the BaseParser interface
2. THE Python_Parser SHALL register the extensions `.py` and `.pyi` with the Parser_Registry
3. THE Python_Parser SHALL produce identical ASTNode and ASTEdge output as the current `xce/parser.py` implementation for the same input files
4. WHEN a Python file contains a syntax error, THE Python_Parser SHALL return partial results or empty lists without raising an exception

### Requirement 4: TypeScript Parser Refactoring

**User Story:** As a maintainer, I want the existing TypeScript parser refactored into the new architecture, so that it uses the TreeSitterBaseParser and conforms to the BaseParser interface.

#### Acceptance Criteria

1. THE TypeScript_Parser SHALL implement the BaseParser interface via TreeSitterBaseParser
2. THE TypeScript_Parser SHALL register the extensions `.ts`, `.tsx`, `.js`, and `.jsx` with the Parser_Registry
3. THE TypeScript_Parser SHALL extract classes, functions, arrow functions, interfaces, type aliases, enums, and imports
4. WHEN a TypeScript file contains a syntax error, THE TypeScript_Parser SHALL return partial results without raising an exception

### Requirement 5: New Language Parsers

**User Story:** As a user with a multi-language codebase, I want XCE to parse Go, Rust, Java, C#, Ruby, PHP, Kotlin, Swift, and C/C++ files, so that I get full architectural context across my entire project.

#### Acceptance Criteria

1. WHEN a Go source file is provided, THE Go_Parser SHALL extract packages, structs, interfaces, functions, methods, and import declarations
2. WHEN a Rust source file is provided, THE Rust_Parser SHALL extract modules, structs, enums, traits, impl blocks, functions, and use declarations
3. WHEN a Java source file is provided, THE Java_Parser SHALL extract packages, classes, interfaces, methods, and import declarations
4. WHEN a C# source file is provided, THE CSharp_Parser SHALL extract namespaces, classes, interfaces, methods, and using declarations
5. WHEN a Ruby source file is provided, THE Ruby_Parser SHALL extract modules, classes, methods, and require statements
6. WHEN a PHP source file is provided, THE PHP_Parser SHALL extract namespaces, classes, interfaces, functions, methods, and use declarations
7. WHEN a Kotlin source file is provided, THE Kotlin_Parser SHALL extract packages, classes, interfaces, functions, and import declarations
8. WHEN a Swift source file is provided, THE Swift_Parser SHALL extract modules, classes, structs, protocols, functions, and import declarations
9. WHEN a C or C++ source file is provided, THE Cpp_Parser SHALL extract namespaces, classes, structs, functions, and include directives
10. EACH Language_Parser SHALL subclass TreeSitterBaseParser and provide only a Node_Type_Mapping configuration
11. EACH Language_Parser SHALL register its supported file extensions with the Parser_Registry

### Requirement 6: Parser Output Consistency

**User Story:** As a downstream consumer of parser output, I want all parsers to produce structurally consistent ASTNode and ASTEdge data, so that the graph construction pipeline works identically regardless of source language.

#### Acceptance Criteria

1. THE ASTNode id field SHALL follow the format `{repo_id}:{filepath}:{kind}:{name}` for all parsers
2. THE ASTNode kind field SHALL use values from the existing NodeKind enum for all parsers
3. EACH parser SHALL produce at least one MODULE-kind ASTNode per file representing the file itself
4. EACH parser SHALL produce CONTAINS edges from parent nodes to child nodes for all nested declarations
5. WHEN a parser encounters a function call, THE parser SHALL produce a CALLS edge from the calling function to the called function
6. WHEN a parser encounters an import statement, THE parser SHALL produce an IMPORT-kind ASTNode

### Requirement 7: Graceful Error Handling

**User Story:** As a user indexing a large repository, I want parsers to handle malformed files gracefully, so that a single broken file does not prevent the rest of the repository from being indexed.

#### Acceptance Criteria

1. WHEN a source file contains syntax errors, THE parser SHALL return partial results for the portions that parsed successfully
2. WHEN a source file cannot be read due to encoding issues, THE parser SHALL log a warning and return empty lists
3. WHEN a source file exceeds 1MB in size, THE parser SHALL skip the file and log a warning
4. IF a tree-sitter grammar fails to load, THEN THE Parser_Registry SHALL log an error and exclude that language from available parsers without crashing

### Requirement 8: Parser Independence

**User Story:** As a developer running parsers concurrently, I want each parser instance to be stateless and independent, so that parsing can be parallelized safely.

#### Acceptance Criteria

1. THE TreeSitterBaseParser SHALL maintain no shared mutable state between parse_file invocations
2. EACH Language_Parser instance SHALL be safe to use from multiple threads without external synchronization
3. THE Parser_Registry SHALL be immutable after initial registration is complete

### Requirement 9: Open Source Repository Preparation

**User Story:** As a project maintainer preparing for open source release, I want the repository to include proper licensing, contributor documentation, and no hardcoded secrets, so that the project is ready for public consumption.

#### Acceptance Criteria

1. THE repository SHALL contain an AGPL-3.0 LICENSE file at the root
2. THE repository SHALL contain a `.env.example` file listing all required environment variables with placeholder values and descriptions
3. THE repository SHALL contain a `CONTRIBUTING.md` file with contribution guidelines
4. THE repository SHALL contain a `COMMERCIAL_LICENSE.md` file explaining the dual licensing model
5. WHEN the `xce/` package is scanned, THE package SHALL contain no hardcoded API keys, tokens, or secrets
6. THE `pyproject.toml` SHALL list all required tree-sitter grammar packages as dependencies
7. THE `pyproject.toml` license field SHALL be updated from "MIT" to "AGPL-3.0-or-later"

### Requirement 10: File Extension Auto-Detection

**User Story:** As a user indexing a repository, I want the system to automatically detect the correct parser for each file based on its extension, so that I do not need to manually configure language mappings.

#### Acceptance Criteria

1. WHEN a repository is indexed, THE Parser_Registry SHALL automatically select the correct parser for each file based on its extension
2. THE Parser_Registry SHALL support at minimum the following extension mappings: `.py`, `.pyi`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`, `.rs`, `.java`, `.cs`, `.rb`, `.php`, `.kt`, `.kts`, `.swift`, `.c`, `.cpp`, `.cc`, `.cxx`, `.h`, `.hpp`
3. WHEN a file has no registered parser, THE indexing pipeline SHALL skip the file without error

