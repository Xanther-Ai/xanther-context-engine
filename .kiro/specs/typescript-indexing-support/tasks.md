# Tasks

## Task 1: Create TypeScript parser module
- [ ] 1.1 Create `scripts/ts_parser.py` with `TypeScriptParser` class using tree-sitter
- [ ] 1.2 Implement `parse_file()` method that extracts modules, classes, functions, interfaces, enums, imports
- [ ] 1.3 Handle arrow functions, async functions, class methods, extends/implements
- [ ] 1.4 Extract JSDoc comments as docstrings
- [ ] 1.5 Generate function signatures

## Task 2: Update pipeline to support multiple languages
- [ ] 2.1 Update `stage1_ast` in `ec2_index_pipeline.py` to discover and parse `.ts/.tsx/.js/.jsx` files
- [ ] 2.2 Update `saas_index_worker.py` to count TS/JS files alongside Python files
- [ ] 2.3 Install tree-sitter dependencies on EC2

## Task 3: Test with lobe-chat repo
- [ ] 3.1 Run the updated pipeline on lobehub/lobe-chat
- [ ] 3.2 Verify nodes appear in Neo4j
- [ ] 3.3 Verify XCE queries return TypeScript context
