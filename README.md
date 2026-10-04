# DealWatch

DealWatch is an AI-powered deal discovery and 14-day price tracking platform across e-commerce retailers and multi-vertical comparison channels.

## Core Features & Architecture
- **Multi-vertical generic core:** Section 10B architecture separating core comparison/tracking abstractions (`subjects`, `sources`, `offers`, `observations`, `trackers`) from vertical-specific models (`product_details`).
- **Vertical #1 (Products):** Deterministic matching hierarchy (GTIN > MPN > SKU > Brand/Model/Variant) and JSON-LD schema.org extraction without stealth scrapers.
- **Client-agnostic MCP Interface:** Streamable HTTP transport at `/mcp` serving both plain text natural-language clients (Claude) and rich interactive widgets (ChatGPT App iframe).
- **Independent Daily Price Worker:** Executes via GitHub Actions cron directly against serverless PostgreSQL (Neon), decoupled from API server cold starts.
- **Deterministic Alerting:** Strictly isolated currencies, price drops, and target thresholds.

## Quick Start

### 1. Environment & Dependencies
Python 3.12+ and `uv` are recommended:
```bash
uv venv --python python3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### 2. Configure Environment
Copy `.env.example` to `.env` and fill in your connection strings:
```bash
cp .env.example .env
```

### 3. Run Migrations
```bash
alembic upgrade head
```

### 4. Run Test Suite
```bash
pytest -v
```

### 5. Start Development Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
