#!/bin/bash
# Setup script for XCE Integration Testing Infrastructure
# This script sets up PostgreSQL and Neo4j for testing

set -e

echo "=========================================="
echo "XCE Test Infrastructure Setup"
echo "=========================================="

# Check for Docker
if command -v docker &> /dev/null; then
    echo "✅ Docker found"
    
    # Start PostgreSQL container
    echo "Starting PostgreSQL..."
    docker run -d \
        --name xce-postgres-test \
        -e POSTGRES_USER=xce \
        -e POSTGRES_PASSWORD=xce_dev_password \
        -e POSTGRES_DB=xce_index \
        -p 5432:5432 \
        postgres:16-alpine
    
    # Initialize schema
    echo "Initializing PostgreSQL schema..."
    sleep 3
    docker exec -i xce-postgres-test psql -U xce -d xce_index < scripts/init-postgres.sql
    
    # Start Neo4j container (if not already running)
    if ! docker ps | grep -q xce-neo4j; then
        echo "Starting Neo4j..."
        docker run -d \
            --name xce-neo4j-test \
            -e NEO4J_AUTH=neo4j/xce_dev_password \
            -e NEO4J_PLUGINS='["apoc"]' \
            -p 7474:7474 \
            -p 7687:7687 \
            neo4j:5-community
    fi
    
    echo "✅ Docker-based setup complete!"
else
    echo "❌ Docker not found. Please install Docker Desktop:"
    echo "   https://www.docker.com/products/docker-desktop"
    echo ""
    echo "Alternative: Install PostgreSQL manually:"
    echo "   brew install postgresql@16"
    echo "   brew services start postgresql@16"
    echo "   createdb xce_index"
    exit 1
fi

echo ""
echo "=========================================="
echo "Services Status:"
echo "=========================================="
docker ps --filter "name=xce-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "To run integration tests:"
echo "  pytest tests/integration/test_incremental_indexing.py -v"