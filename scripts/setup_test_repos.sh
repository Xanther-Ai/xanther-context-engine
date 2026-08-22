#!/bin/bash
# Xanther Test Repo Setup
# Clones all test repos into ~/xanther-test-repos
# Usage: bash scripts/setup_test_repos.sh

set -e

REPOS_DIR="$HOME/xanther-test-repos"
mkdir -p "$REPOS_DIR"

echo "=== Xanther Test Repo Setup ==="
echo "Target dir: $REPOS_DIR"
echo ""

clone_or_update() {
    local name="$1"
    local url="$2"
    local dir="$REPOS_DIR/$name"

    if [ -d "$dir/.git" ]; then
        echo "  ✓ $name already cloned — skipping (delete dir to re-clone)"
    else
        echo "  Cloning $name..."
        git clone --depth 1 "$url" "$dir"
        echo "  ✓ $name cloned"
    fi
}

clone_or_update "fastapi"  "https://github.com/tiangolo/fastapi"
clone_or_update "celery"   "https://github.com/celery/celery"
clone_or_update "httpx"    "https://github.com/encode/httpx"
clone_or_update "express"  "https://github.com/expressjs/express"
clone_or_update "flask"    "https://github.com/pallets/flask"

echo ""
echo "=== All repos ready ==="
echo ""
echo "Next steps:"
echo ""
echo "  # Test one repo in XME-only mode (fast, no LLM docs):"
echo "  python scripts/run_repo_test.py --repo fastapi --mode xme"
echo ""
echo "  # Test one repo in full mode (XCE + XME, all 4 layers):"
echo "  python scripts/run_repo_test.py --repo fastapi --mode full"
echo ""
echo "  # Run both modes and compare:"
echo "  python scripts/run_repo_test.py --repo fastapi --mode all"
echo ""
echo "  # Recommended order (fast to slow):"
echo "  1. httpx   — smallest, quickest to index"
echo "  2. flask   — medium, good episodic memory test"
echo "  3. fastapi — medium, good architecture test"
echo "  4. express — tests JS parser"
echo "  5. celery  — largest, real small-model stress test"
echo ""
echo "Results go in: docs/test-results/"
