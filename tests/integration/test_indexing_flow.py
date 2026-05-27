"""End-to-end integration tests for the indexing flow.

Tests the full pipeline: Submit repo → SQS message → job status updates
→ tenant-scoped graph data.

Uses moto for DynamoDB and SQS mocking.

Validates: Requirements 7.1, 7.2, 7.3
"""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from services.auth.auth_service import AuthService
from services.indexing.indexing_service import IndexingJobService
from services.indexing.task_runner import IndexTaskRunner
from services.shared.models import IndexJobStatus, SubscriptionTier


# ---------------------------------------------------------------------------
# DynamoDB + SQS table/queue creation helpers
# ---------------------------------------------------------------------------

def _create_tables(dynamodb):
    """Create all DynamoDB tables needed for the indexing integration tests."""
    # xce-users
    dynamodb.create_table(
        TableName="xce-users",
        KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # xce-api-keys (needed by AuthService)
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

    # xce-index-jobs (PK: user_id, SK: job_id, GSI: repo-index on repo_id)
    dynamodb.create_table(
        TableName="xce-index-jobs",
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "job_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "job_id", "AttributeType": "S"},
            {"AttributeName": "repo_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "repo-index",
                "KeySchema": [
                    {"AttributeName": "repo_id", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_sqs_queue(sqs_client) -> str:
    """Create a mock SQS queue and return its URL."""
    resp = sqs_client.create_queue(QueueName="xce-index-queue")
    return resp["QueueUrl"]


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
def moto_aws(aws_env):
    """Provide moto-mocked DynamoDB resource and SQS client."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        sqs = boto3.client("sqs", region_name="us-east-1")
        _create_tables(ddb)
        queue_url = _create_sqs_queue(sqs)
        yield ddb, sqs, queue_url


@pytest.fixture
def auth_service(moto_aws):
    ddb, _, _ = moto_aws
    return AuthService(ddb)


@pytest.fixture
def indexing_service(moto_aws):
    ddb, sqs, queue_url = moto_aws
    return IndexingJobService(
        dynamodb_resource=ddb,
        sqs_client=sqs,
        queue_url=queue_url,
    )


@pytest.fixture
def task_runner(moto_aws):
    ddb, sqs, queue_url = moto_aws
    return IndexTaskRunner(
        sqs_client=sqs,
        dynamodb_resource=ddb,
        queue_url=queue_url,
    )


@pytest.fixture
def sqs_client(moto_aws):
    _, sqs, _ = moto_aws
    return sqs


@pytest.fixture
def queue_url(moto_aws):
    _, _, url = moto_aws
    return url


# ---------------------------------------------------------------------------
# Helper: seed a user
# ---------------------------------------------------------------------------

async def _create_user(
    auth_service: AuthService,
    user_id: str = "user-idx-001",
    email: str = "idx@example.com",
    tier: str = "free",
) -> str:
    """Create a user, optionally override tier. Returns user_id."""
    await auth_service.get_or_create_user(
        {"sub": user_id, "email": email, "name": "Index Test User"}
    )
    if tier != "free":
        auth_service.users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET tier = :t",
            ExpressionAttributeValues={":t": tier},
        )
    return user_id


# ===================================================================
# Test 1: Submit indexing job → QUEUED status + SQS message
# ===================================================================

async def test_submit_job_creates_record_and_sqs_message(
    auth_service, indexing_service, sqs_client, queue_url
):
    """Submitting a repo creates a DynamoDB record with QUEUED status and
    sends a correctly-shaped SQS message."""
    user_id = await _create_user(auth_service)

    job = await indexing_service.submit_job(
        user_id=user_id,
        repo_url="https://github.com/octocat/Hello-World",
        branch="main",
    )

    # Verify DynamoDB record
    assert job.status == IndexJobStatus.QUEUED
    assert job.user_id == user_id
    assert job.repo_url == "https://github.com/octocat/Hello-World"
    assert job.repo_id == f"{user_id}:Hello-World"
    assert job.progress_pct == 0

    # Verify the job is retrievable via get_job_status
    fetched = await indexing_service.get_job_status(job.job_id, user_id)
    assert fetched is not None
    assert fetched.status == IndexJobStatus.QUEUED

    # Verify SQS message was sent
    resp = sqs_client.receive_message(
        QueueUrl=queue_url, MaxNumberOfMessages=1
    )
    messages = resp.get("Messages", [])
    assert len(messages) == 1

    body = json.loads(messages[0]["Body"])
    assert body["job_id"] == job.job_id
    assert body["user_id"] == user_id
    assert body["repo_url"] == "https://github.com/octocat/Hello-World"
    assert body["repo_id"] == f"{user_id}:Hello-World"
    assert body["branch"] == "main"


# ===================================================================
# Test 2: Job status is tenant-scoped — user A cannot see user B's jobs
# ===================================================================

async def test_job_status_tenant_isolation(auth_service, indexing_service):
    """User A cannot see User B's indexing jobs via get_job_status."""
    user_a = await _create_user(auth_service, user_id="user-A", email="a@x.com")
    user_b = await _create_user(auth_service, user_id="user-B", email="b@x.com")

    # User A submits a job
    job_a = await indexing_service.submit_job(
        user_id=user_a,
        repo_url="https://github.com/octocat/Hello-World",
    )

    # User A can see their own job
    result_a = await indexing_service.get_job_status(job_a.job_id, user_a)
    assert result_a is not None
    assert result_a.job_id == job_a.job_id

    # User B cannot see User A's job
    result_b = await indexing_service.get_job_status(job_a.job_id, user_b)
    assert result_b is None

    # User B's repo list should be empty
    user_b_repos = await indexing_service.list_user_repos(user_b)
    assert len(user_b_repos) == 0


# ===================================================================
# Test 3: Repo URL validation — invalid URLs are rejected
# ===================================================================

async def test_invalid_repo_url_rejected(auth_service, indexing_service):
    """Invalid repo URLs are rejected with ValueError."""
    user_id = await _create_user(auth_service)

    invalid_urls = [
        "not-a-url",
        "http://github.com/user/repo",       # HTTP, not HTTPS
        "https://gitlab.com/user/repo",       # Not GitHub
        "ftp://github.com/user/repo",
        "",
    ]

    for url in invalid_urls:
        with pytest.raises(ValueError, match="valid HTTPS GitHub URL"):
            await indexing_service.submit_job(user_id=user_id, repo_url=url)


# ===================================================================
# Test 4: Tier-based repo limit enforcement — Free tier limited to 2
# ===================================================================

async def test_free_tier_repo_limit_enforcement(auth_service, indexing_service):
    """Free tier users are limited to 2 repos. Third submission is rejected."""
    user_id = await _create_user(auth_service, tier="free")

    # Submit 2 repos (the free tier limit)
    await indexing_service.submit_job(
        user_id=user_id,
        repo_url="https://github.com/octocat/repo-one",
    )
    await indexing_service.submit_job(
        user_id=user_id,
        repo_url="https://github.com/octocat/repo-two",
    )

    # Third repo should be rejected
    with pytest.raises(ValueError, match="Repo limit reached"):
        await indexing_service.submit_job(
            user_id=user_id,
            repo_url="https://github.com/octocat/repo-three",
        )

    # Verify only 2 jobs exist
    repos = await indexing_service.list_user_repos(user_id)
    assert len(repos) == 2


# ===================================================================
# Test 5: repo_id is correctly scoped as {user_id}:{repo_name}
# ===================================================================

async def test_repo_id_scoped_correctly(auth_service, indexing_service):
    """repo_id is formatted as {user_id}:{repo_name}, extracting repo name
    from the GitHub URL."""
    user_id = await _create_user(auth_service)

    job = await indexing_service.submit_job(
        user_id=user_id,
        repo_url="https://github.com/xanther/context-engine",
    )
    assert job.repo_id == f"{user_id}:context-engine"

    # Also works with .git suffix
    job2 = await indexing_service.submit_job(
        user_id=user_id,
        repo_url="https://github.com/xanther/another-repo.git",
    )
    assert job2.repo_id == f"{user_id}:another-repo"
