#!/bin/bash

# Xanther Local - Setup Verification Script
# Run this to verify all systems are working

set +e  # Don't exit on errors

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  XANTHER LOCAL - SETUP VERIFICATION                           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PASS=0
FAIL=0
WARN=0

check_service() {
    local name=$1
    local url=$2
    local timeout=$3
    
    if timeout "$timeout" curl -s "$url" >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} $name"
        ((PASS++))
        return 0
    else
        echo -e "${RED}✗${NC} $name"
        ((FAIL++))
        return 1
    fi
}

warn_service() {
    local name=$1
    echo -e "${YELLOW}○${NC} $name"
    ((WARN++))
}

echo "SERVICES:"
check_service "Dashboard API (localhost:8080)" "http://localhost:8080/api/health" "3" || \
    echo "     → Start with: python3 -m xce.dashboard.server"
check_service "MCP Server (localhost:8001)" "http://localhost:8001/mcp/call" "3" || \
    echo "     → Start with: python3 -m xce.server.http_mcp_server"

echo ""
echo "DATABASE:"

# Check Neo4j
if python3 << 'PYEOF' 2>/dev/null; then
import asyncio
from neo4j import AsyncGraphDatabase

async def check():
    try:
        driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "xce_dev_password"))
        async with driver.session() as session:
            result = await session.run("MATCH (n:ASTNode) RETURN COUNT(*) as count")
            record = await result.single()
            count = record["count"]
            print(f"Neo4j nodes: {count}")
            await driver.close()
            return count > 0
    except Exception as e:
        print(f"Neo4j error: {e}")
        return False

result = asyncio.run(check())
exit(0 if result else 1)
PYEOF
then
    echo -e "${GREEN}✓${NC} Neo4j Database"
    ((PASS++))
else
    echo -e "${RED}✗${NC} Neo4j Database"
    ((FAIL++))
    echo "     → Start with: cd neo4j-community-5.26.0 && bin/neo4j console"
fi

echo ""
echo "CLI:"

# Check xanther-cli
if npx xanther-cli --version >/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} xanther-cli"
    ((PASS++))
else
    echo -e "${YELLOW}○${NC} xanther-cli not found (optional)"
    ((WARN++))
    echo "     → Install with: npm install -g xanther-cli"
fi

echo ""
echo "CONFIGURATION:"

# Check .xanther config
if [ -f ~/.xanther/config.json ]; then
    if grep -q "use_local" ~/.xanther/config.json 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Local mode configured"
        ((PASS++))
    else
        echo -e "${YELLOW}○${NC} Local mode not configured"
        ((WARN++))
        echo "     → Run: npx xanther-cli init --local"
    fi
else
    echo -e "${YELLOW}○${NC} No xanther config (optional)"
    ((WARN++))
    echo "     → Run: npx xanther-cli init --local"
fi

# Check MCP config
if [ -f ~/.kiro/settings/mcp.json ]; then
    if grep -q "xanther-local\|xce.server.http_mcp_server" ~/.kiro/settings/mcp.json 2>/dev/null; then
        echo -e "${GREEN}✓${NC} MCP configured for Kiro"
        ((PASS++))
    else
        warn_service "MCP not configured for Kiro (optional)"
    fi
else
    warn_service "Kiro MCP config not found (optional)"
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}✅ ALL SYSTEMS OPERATIONAL!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. cd /path/to/your/repo"
    echo "  2. npx xanther-cli init --local"
    echo "  3. npx xanther-cli sync --local"
    echo ""
    echo "Then query via:"
    echo "  • REST API: http://localhost:8080/api/symbol/{id}/callers"
    echo "  • MCP: xce_search tool in Kiro/Cursor"
    echo ""
else
    echo -e "${RED}❌ SOME SYSTEMS OFFLINE${NC}"
    echo ""
    echo "Fix the following:"
    if ! check_service "tmp" "http://localhost:8080/api/health" "1" >/dev/null 2>&1; then
        echo "  • Dashboard API: python3 -m xce.dashboard.server"
    fi
    if ! check_service "tmp" "http://localhost:8001/mcp/call" "1" >/dev/null 2>&1; then
        echo "  • MCP Server: python3 -m xce.server.http_mcp_server"
    fi
    echo "  • Neo4j: cd neo4j-community-5.26.0 && bin/neo4j console"
    echo ""
fi

echo "Summary: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}, ${YELLOW}$WARN warnings${NC}"
echo ""

exit $FAIL
