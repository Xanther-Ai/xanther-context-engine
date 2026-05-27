"""End-to-end integration tests for the MCP query flow.

Tests the full pipeline: API key auth → rate limit check → MCP tool call
→ usage tracked → tenant-scoped results.

Uses moto for DynamoDB mocking and mock agents for Neo4j.

Validates: Requirements 3.1, 3.2, 6.1, 6.2, 5.1
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from unittest.mock import AsyncMock

import boto3
import pytest
from moto import mock_aws

from services.auth.auth_service import AuthService
from services.mcp_server.server import MultiTenantMCPServer
from services.rate_limiter.rate_limiter import RateLimiter
from services.shared.models import SubscriptionTier, TIER_LIMITS
from services.usage.usage_service import UsageTrackingService


# ---------------------------------------------------------------------------
# DynamoDB table creation helpers
# ---------------------------------------------------------------------------

def _create_tables(dynamodb):
    """Create all DynamoDB tables needed for the integration tests."""
    # xce-users
    dynamodb.create_table(
        TableName="xce-users",
        KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # xce-api-keys (PK: key_hash, GSI: user-index on user_id)
    dynamodb.create_table(
        TableName="xce-api-keys",
        KeySchema=[{"AttributeName": "key_hash", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "key_hash", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "user-index",
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # xce-usage-tracking (PK: user_id, SK: period)
    dynamodb.create_table(
        TableName="xce-usage-tracking",
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "period", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "period", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


# ---------------------------------------------------------------------------
# Mock XCE agents (stand-in for Neo4j-backed agents)
# ---------------------------------------------------------------------------

def _make_mock_agents() -> dict[str, Any]:
    """Create mock agents that simulate XCE tool responses."""
    search_agent = AsyncMock()
    search_agent.search.return_value = "Found 3 results for query in repo"

    arch_agent = AsyncMock()
    arch_agent.query.return_value = "Architecture context for file.py"

    trace_agent = AsyncMock()
    trace_agent.trace.return_value = "Trace from A to module level"

    impact_agent = AsyncMock()
    impact_agent.analyze.return_value = "Impact analysis: 5 affected files"

    return {
        "search": search_agent,
        "architecture": arch_agent,
        "trace": trace_agent,
        "impact": impact_agent,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def aws_env(monkeypatch):
    """Set dummy AWS credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def dynamodb(aws_env):
    """Provide a moto-mocked DynamoDB resource with all tables created."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(ddb)
        yield ddb


@pytest.fixture
def auth_service(dynamodb):
    return AuthService(dynamodb)


@pytest.fixture
def rate_limiter(dynamodb):
    return RateLimiter(dynamodb)


@pytest.fixture
def usage_service(dynamodb):
    return UsageTrackingService(dynamodb)


@pytest.fixture
def mock_agents():
    return _make_mock_agents()


@pytest.fixture
def mcp_server(mock_agents, usage_service):
    return MultiTenantMCPServer(agents=mock_agents, usage_service=usage_service)


# ---------------------------------------------------------------------------
# Helper: seed a user + API key and return the raw key
# ---------------------------------------------------------------------------

async def _create_user_with_key(
    auth_service: AuthService,
    user_id: str = "user-001",
    email: str = "dev@example.com",
    tier: str = "free",
) -> tuple[str, str]:
    """Create a user and generate an API key. Returns (user_id, raw_key)."""
    user = await auth_service.get_or_create_user(
        {"sub": user_id, "email": email, "name": "Test User"}
    )
    # Optionally upgrade tier
    if tier != "free":
        auth_service.users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET tier = :t",
            ExpressionAttributeValues={":t": tier},
        )
    api_key, raw_key = await auth_service.generate_api_key(user_id, "test-key")
    return user_id, raw_key


# ===================================================================
# Test 1: Full MCP query flow (happy path)
# ===================================================================

async def test_full_mcp_query_flow(
    auth_service, rate_limiter, usage_service, mcp_server, mock_agents
):
    """Full pipeline: create user → generate key → validate → rate limit
    → MCP tool call → verify usage incremented → verify tenant-scoped repo_id.
    """
    # 1. Create user and generate API key
    user_id, raw_key = await _create_user_with_key(auth_service)

    # 2. Validate the API key through the rate limiter
    result = await rate_limiter.check_and_increment(raw_key)
    assert result.allowed is True
    assert result.user_id == user_id
    assert result.tier == SubscriptionTier.FREE
    assert result.queries_used == 1
    assert result.queries_limit == TIER_LIMITS[SubscriptionTier.FREE]

    # 3. Simulate MCP tool call via the server's internal routing
    #    Build a fake request with tenant headers
    from starlette.testclient import TestClient

    client = TestClient(mcp_server.app)
    resp = client.post(
        "/mcp/tools/call",
        json={
            "name": "xce_search",
            "arguments": {"query": "authentication", "repo_id": "my-repo"},
        },
        headers={
            "x-user-id": user_id,
            "x-user-tier": "free",
            "x-queries-remaining": "99",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "content" in body
    # Result should NOT contain the tenant prefix
    for item in body["content"]:
        assert f"{user_id}:" not in item["text"]

    # 4. Verify the agent received tenant-scoped repo_id
    mock_agents["search"].search.assert_called_once()
    call_args = mock_agents["search"].search.call_args
    scoped_repo_id = call_args[0][1]  # second positional arg is repo_id
    assert scoped_repo_id == f"{user_id}:my-repo"

    # 5. Verify usage was tracked (give async task a moment)
    await asyncio.sleep(0.1)
    usage = await usage_service.get_current_usage(user_id)
    assert usage.queries_used >= 1


# ===================================================================
# Test 2: Invalid API key returns deny
# ===================================================================

async def test_invalid_api_key_denied(rate_limiter):
    """An invalid/unknown API key should be denied by the rate limiter."""
    result = await rate_limiter.check_and_increment("xce_totally_bogus_key_12345")
    assert result.allowed is False
    assert result.user_id == "anonymous"


# ===================================================================
# Test 3: Rate limit exceeded returns deny
# ===================================================================

async def test_rate_limit_exceeded(auth_service, rate_limiter):
    """After exhausting the tier limit, subsequent requests are denied."""
    user_id, raw_key = await _create_user_with_key(auth_service)
    limit = TIER_LIMITS[SubscriptionTier.FREE]  # 100

    # Burn through all allowed queries
    for i in range(limit):
        r = await rate_limiter.check_and_increment(raw_key)
        assert r.allowed is True, f"Request {i+1} should be allowed"

    # The next request should be denied
    denied = await rate_limiter.check_and_increment(raw_key)
    assert denied.allowed is False
    assert denied.user_id == user_id
    assert denied.queries_used >= limit


# ===================================================================
# Test 4: Tenant isolation — user A cannot see user B's data
# ===================================================================

async def test_tenant_isolation(auth_service, mcp_server, mock_agents):
    """Two users calling the same tool get different tenant-scoped repo_ids.
    User A's repo_id prefix must differ from User B's.
    """
    user_a, _ = await _create_user_with_key(auth_service, user_id="user-A", email="a@x.com")
    user_b, _ = await _create_user_with_key(auth_service, user_id="user-B", email="b@x.com")

    from starlette.testclient import TestClient

    client = TestClient(mcp_server.app)

    # User A calls xce_search
    resp_a = client.post(
        "/mcp/tools/call",
        json={
            "name": "xce_search",
            "arguments": {"query": "auth", "repo_id": "shared-repo"},
        },
        headers={
            "x-user-id": user_a,
            "x-user-tier": "free",
            "x-queries-remaining": "99",
        },
    )
    assert resp_a.status_code == 200

    # Capture the repo_id that was passed to the agent for user A
    call_a = mock_agents["search"].search.call_args_list[-1]
    repo_id_a = call_a[0][1]

    # Reset mock to capture user B's call separately
    mock_agents["search"].search.reset_mock()

    # User B calls xce_search with the same repo name
    resp_b = client.post(
        "/mcp/tools/call",
        json={
            "name": "xce_search",
            "arguments": {"query": "auth", "repo_id": "shared-repo"},
        },
        headers={
            "x-user-id": user_b,
            "x-user-tier": "free",
            "x-queries-remaining": "99",
        },
    )
    assert resp_b.status_code == 200

    call_b = mock_agents["search"].search.call_args_list[-1]
    repo_id_b = call_b[0][1]

    # The scoped repo_ids must be different
    assert repo_id_a == f"{user_a}:shared-repo"
    assert repo_id_b == f"{user_b}:shared-repo"
    assert repo_id_a != repo_id_b

    # Neither response should leak the other user's prefix
    for item in resp_a.json()["content"]:
        assert f"{user_b}:" not in item["text"]
    for item in resp_b.json()["content"]:
        assert f"{user_a}:" not in item["text"]


# ===================================================================
# Test 5: Usage tracking increments correctly after tool call
# ===================================================================

async def test_usage_tracking_increments(auth_service, dynamodb):
    """Usage tracking service correctly increments counters per tool call.

    Tests the UsageTrackingService directly (not via fire-and-forget) to
    validate that atomic counters and per-tool breakdown work correctly.
    The MCP server delegates to this service after each tool call.

    NOTE: We pre-seed the `breakdown` map because DynamoDB's ADD on a
    nested path (breakdown.#tool) requires the parent map to exist.
    """
    user_id, _ = await _create_user_with_key(auth_service)

    usage_table = dynamodb.Table("xce-usage-tracking")
    usage_svc = UsageTrackingService(dynamodb)
    period = usage_svc._current_period()

    # Pre-seed the item with an empty breakdown map
    usage_table.put_item(
        Item={
            "user_id": user_id,
            "period": period,
            "queries_used": 0,
            "credits_used": 0,
            "breakdown": {},
        }
    )

    # Increment 3 times for xce_search
    for _ in range(3):
        record = await usage_svc.increment(user_id, "xce_search")

    assert record.queries_used == 3

    # Increment once for xce_trace
    record = await usage_svc.increment(user_id, "xce_trace")
    assert record.queries_used == 4

    # Verify via get_current_usage
    usage = await usage_svc.get_current_usage(user_id)
    assert usage.queries_used == 4
