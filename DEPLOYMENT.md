# XCE Deployment Guide

## Local Development

### Prerequisites
- Python 3.12+
- Docker & Docker Compose

### Quick Start

```bash
# Start Neo4j
docker compose up neo4j -d

# Install dependencies
pip install -e ".[dev]"

# Copy and configure environment
cp .env.example .env  # Edit with your API keys

# Run MCP server locally (stdio)
python -m xce.mcp_server

# Run MCP server (SSE mode)
python -m xce.mcp_server --sse
```

### Full Stack (App + Neo4j)

```bash
docker compose up --build
```

The XCE MCP server will be available at `http://localhost:8000`.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEO4J_URI` | Yes | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | Yes | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | Yes | — | Neo4j password |
| `OPENROUTER_API_KEY` | Yes | — | OpenRouter API key for embeddings and LLM |
| `KIMI_API_KEY` | Yes | — | Kimi/Moonshot API key for summarization |
| `EMBEDDING_MODEL` | No | `openai/text-embedding-3-small` | Embedding model |
| `EMBEDDING_DIMENSIONS` | No | `512` | Embedding vector dimensions |
| `SUMMARIZER_MODEL` | No | `moonshot/kimi-k2.5` | Summarizer model |
| `DOC_GEN_BATCH_SIZE` | No | `10` | Doc generation batch size |
| `EMBEDDING_BATCH_SIZE` | No | `100` | Embedding batch size |
| `RUN_POD_API_KEY` | For deploy | — | RunPod API key |

## RunPod Deployment

### Prerequisites
- Docker registry access (Docker Hub, GHCR, etc.)
- RunPod account with API key

### Deploy

```bash
export DOCKER_REGISTRY=docker.io/youruser
export RUN_POD_API_KEY=your_key
./deploy/runpod_deploy.sh
```

### RunPod Configuration
- **Pod type**: CPU (no GPU required)
- **CPU**: 4 cores
- **Memory**: 16 GB
- **Storage**: 50 GB persistent volume (Neo4j data + repo storage)
- **Ports**: 8000 (HTTP/MCP), 7687 (Neo4j Bolt), 7474 (Neo4j Browser)

### Cost Estimates
- **RunPod CPU pod**: ~$0.03/hr (~$22/month)
- **OpenRouter API**: Variable, ~$0.01-0.05 per indexing run
- **Kimi API**: Variable, ~$0.001 per summarization call
- **Total estimated**: ~$25-30/month for moderate usage

## API Key Setup

1. **OpenRouter**: Sign up at [openrouter.ai](https://openrouter.ai), create an API key
2. **Kimi/Moonshot**: Sign up at [moonshot.ai](https://platform.moonshot.cn), create an API key
3. **RunPod** (optional): Sign up at [runpod.io](https://www.runpod.io), create an API key

## Architecture

```
┌─────────────────────────────────────┐
│           RunPod CPU Pod            │
│                                     │
│  ┌──────────┐    ┌──────────────┐   │
│  │ XCE App  │───▶│   Neo4j DB   │   │
│  │ (FastAPI) │    │ (Container)  │   │
│  └────┬─────┘    └──────────────┘   │
│       │                             │
└───────┼─────────────────────────────┘
        │
        ▼ External APIs
  ┌─────────────┐  ┌──────────┐
  │  OpenRouter  │  │ Kimi/GLM │
  │ (Embeddings) │  │(Summary) │
  └─────────────┘  └──────────┘
```
