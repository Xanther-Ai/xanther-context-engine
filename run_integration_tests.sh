#!/bin/bash
# XCE Integration Test Runner
# This script runs the integration tests for the incremental indexing feature

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "XCE Incremental Indexing - Test Runner"
echo "=========================================="

# Activate virtual environment
source .venv/bin/activate

# Check Neo4j
echo ""
echo "Checking Neo4j..."
if python -c "
import asyncio
from neo4j import AsyncGraphDatabase
async def check():
    driver = AsyncGraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'xce_dev_password'))
    await driver.verify_connectivity()
    await driver.close()
asyncio.run(check())
" 2>/dev/null; then
    echo "  ✅ Neo4j is running"
else
    echo "  ❌ Neo4j is NOT running at bolt://localhost:7687"
fi

# Check PostgreSQL
echo ""
echo "Checking PostgreSQL..."
if python -c "
import asyncpg
import asyncio
async def check():
    conn = await asyncpg.connect('postgresql://xce:xce_dev_password@localhost:5432/xce_index')
    await conn.close()
asyncio.run(check())
" 2>/dev/null; then
    echo "  ✅ PostgreSQL is running"
else
    echo "  ❌ PostgreSQL is NOT running at postgresql://localhost:5432"
    echo ""
    echo "To start services with Docker:"
    echo "  docker-compose up -d"
    echo ""
    echo "Or manually install and start PostgreSQL:"
    echo "  brew install postgresql@16"
    echo "  brew services start postgresql@16"
    echo "  createdb -U postgres xce_index"
    echo "  psql -U postgres -d xce_index -f scripts/init-postgres.sql"
fi

echo ""
echo "=========================================="
echo "Running Tests"
echo "=========================================="

# Run all tests (they will skip if services are unavailable)
python -m pytest tests/integration/test_incremental_indexing.py -v --tb=short

echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo ""
echo "To run a specific test category:"
echo "  pytest tests/integration/test_incremental_indexing.py::TestFileHashing -v"
echo "  pytest tests/integration/test_incremental_indexing.py::TestHashStore -v"
echo "  pytest tests/integration/test_incremental_indexing.py::TestIncrementalIndexing -v"
echo ""
echo "To run tests that don't require external services:"
echo "  pytest tests/integration/test_incremental_indexing.py::TestFileHashing -v"
echo "  pytest tests/integration/test_incremental_indexing.py::TestHashStoreWithMock -v"
echo "  pytest tests/integration/test_incremental_indexing.py::TestIncrementalIndexingLogic -v"