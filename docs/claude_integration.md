# Claude Integration Guide: DealWatch MCP Connector

This guide explains how to connect **DealWatch** to **Claude** (Claude Desktop, Claude Code, and Claude.ai Web) to enable conversational deal discovery, competitor price verification, and 14-day price tracking.

---

## 1. Overview & Architecture

DealWatch implements the official **Model Context Protocol (MCP)** specification. When connected, Claude automatically gains access to DealWatch's 10 standardized tools:

| MCP Tool | Purpose | Example Natural Prompt |
| :--- | :--- | :--- |
| `identify_subject` | Extracts and normalizes product details from links or text. | *"Find deals for this: https://www.croma.com/p/..."* |
| `find_offers` | Returns lowest verified competitor prices (exact matches). | *"Is there any store selling this cheaper right now?"* |
| `submit_offer_url` | Validates a competitor link found via Claude search. | *"I found it on Flipkart at https://..., is it an exact match?"* |
| `track_subject` | Begins a 14-day price tracking job (max 5 active per user). | *"Track this for 14 days and alert me if it drops below 70k."* |
| `list_trackers` | Lists all monitored products for the current user. | *"What products am I currently tracking?"* |
| `get_tracking_status`| Shows countdown days remaining, current prices, and alerts. | *"What is the status of my iPhone tracker?"* |
| `update_tracker` | Adjusts target price or alert triggers on an active tracker. | *"Change my target price on the laptop to 85,000 INR."* |
| `stop_tracking` | Terminates tracking early and frees user quota. | *"Stop tracking the headphones."* |
| `get_price_history` | Returns chronological observations without price erasures. | *"Show me the price trend for this item."* |
| `compare_quotes` | Quote comparison engine (reserved for travel verticals). | *"Compare flight quotes from BOM to DEL."* |

---

## 2. Connecting Claude Desktop (Mac & Windows)

Claude Desktop is completely free to download and supports local or remote MCP servers.

### Configuration File Locations
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

### Option A: Connect to Deployed Remote Server (Render)
If you deployed DealWatch to Render (or any cloud host), use `mcp-remote` to bridge Claude Desktop to your Streamable HTTP endpoint:

```json
{
  "mcpServers": {
    "dealwatch": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://<your-render-subdomain>.onrender.com/mcp"
      ]
    }
  }
}
```

### Option B: Native Local Stdio Connection (Zero Network Latency)
To run DealWatch directly on your machine without deploying:

```json
{
  "mcpServers": {
    "dealwatch": {
      "command": "/Users/samarthsingh/Desktop/Programs/compare/.venv/bin/python",
      "args": [
        "-m",
        "app.mcp.stdio"
      ],
      "cwd": "/Users/samarthsingh/Desktop/Programs/compare",
      "env": {
        "PYTHONPATH": "/Users/samarthsingh/Desktop/Programs/compare"
      }
    }
  }
}
```

*(Restart Claude Desktop after updating this file. You will see a hammer icon 🔨 in the bottom right corner with all DealWatch tools enabled).*

---

## 3. Connecting Claude Code CLI

If you use Anthropic's **Claude Code** terminal agent:

```bash
# Add the remote DealWatch MCP server
claude mcp add dealwatch https://<your-render-subdomain>.onrender.com/mcp
```

Verify with:
```bash
claude mcp list
```

---

## 4. Connecting Claude.ai Web (Custom Connectors)

For Claude.ai Web:
1. Log in to **Claude.ai** (requires Claude Pro / Team / Enterprise plan for custom connectors).
2. Go to **Settings** -> **Connectors** (or **Integrations**).
3. Click **Add Custom Connector**.
4. Enter:
   - **Name**: `DealWatch`
   - **URL**: `https://<your-render-subdomain>.onrender.com/mcp`
   - **Transport**: `Streamable HTTP / Server-Sent Events (SSE)`
5. Save the connector and start a new chat with DealWatch enabled.

---

## 5. Important Plan & Host Limitations

### 1. Render Free-Tier Cold Starts
- Render free instances spin down after **15 minutes of inactivity**.
- The first tool call after hibernation can take **30–50 seconds** while the container boots up.
- **Tip**: If Claude reports a timeout on the first call, simply retry or send a preliminary message while the container warms up. Once awake, all tool executions take < 300ms.

### 2. Multi-Tenant Tracking Quotas
- Every user is capped at **5 active trackers** on the free tier (`MAX_ACTIVE_TRACKERS_PER_USER=5`).
- Attempting to track a 6th item will prompt Claude to say: *"Active tracker limit reached (5/5). Would you like to stop an existing tracker first?"*

---

## 6. Example Prompts to Test with Claude

### Prompt 1: Identifying a Product & Finding Cheaper Deals
> **User**: *"Can you check if there is a cheaper deal for this product? https://www.croma.com/apple-iphone-15-128gb-blue-/p/300652"*
>
> **Claude Actions**:
> 1. Calls `identify_subject(url="https://www.croma.com/...")` -> Extracts Title, GTIN, MPN, Brand, Price (`75,000 INR`).
> 2. Calls `find_offers(subject_id=...)` -> Ranks verified exact competitor offers lowest-first.
> 3. Formats response: *"I identified the Apple iPhone 15 (128GB, Blue). Croma currently lists it at ₹75,000. Reliance Digital has it verified for ₹71,990 (saving ₹3,010)!"*

### Prompt 2: Starting a 14-Day Price Tracker
> **User**: *"Track this for 14 days and let me know if it drops below 70,000 INR."*
>
> **Claude Actions**:
> 1. Calls `track_subject(subject_id=..., target_price=70000.0, target_currency="INR")`.
> 2. Confirms: *"I have started 14-day price tracking for your iPhone 15 with a target price of ₹70,000. Daily checks will run automatically, and you'll receive an email alert if a price drop occurs."*

### Prompt 3: Viewing Monitored Trackers
> **User**: *"What items am I tracking?"*
>
> **Claude Actions**:
> 1. Calls `list_trackers(status="active")`.
> 2. Summarizes all active trackers with target prices and countdowns.

### Prompt 4: Price History Integrity
> **User**: *"Has this price dropped recently?"*
>
> **Claude Actions**:
> 1. Calls `get_price_history(offer_id=...)`.
> 2. Displays historical point-in-time price observations.
