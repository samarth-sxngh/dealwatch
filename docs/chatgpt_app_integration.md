# ChatGPT App Integration Guide: Interactive DealWatch Card Widget

This document details the architecture, configuration, and verification for the **DealWatch ChatGPT App UI**. DealWatch leverages the Model Context Protocol (MCP) UI extension and ChatGPT Apps SDK to render rich, interactive deal discovery cards directly within ChatGPT conversations.

---

## 1. Overview & Architecture

When ChatGPT invokes DealWatch tools (such as `find_offers`, `track_subject`, or `get_tracking_status`), the response includes metadata pointing to a registered MCP UI resource template:

```json
{
  "status": "success",
  "_meta": {
    "openai/outputTemplate": "ui://dealwatch/widget.html"
  },
  "subject_id": "...",
  "product_title": "Sony WH-1000XM5 Wireless Headphones",
  "lowest_verified_price": 24990.0,
  "lowest_verified_retailer": "Amazon India",
  "verified_offers": [...]
}
```

ChatGPT fetches the UI resource template from `ui://dealwatch/widget.html` via the MCP server and renders it inside an isolated, sandboxed iframe.

### Key Capabilities of the DealWatch Card:
1. **Hero Price Display**: Highlights the lowest verified retailer price, savings amount, and stock status.
2. **SVG Price History Sparkline**: Renders an inline SVG trend line directly from historical observations with zero external charting dependencies.
3. **Verified Competitor Table**: Lists exact-match competitor offers sorted lowest-price-first, complete with direct retailer links and domain tags.
4. **Isolated Uncertain Offers**: Automatically places condition mismatches, open-box offers, or unverified listings in a collapsible warning section.
5. **Two-Way Interactive Tracking**:
   - Users can type a custom target price threshold.
   - Clicking **"Track Price"** invokes `track_subject` via `window.openai.callTool(...)`.
   - Clicking **"Stop Tracking"** invokes `stop_tracking` to release user quota.
   - All interactive state updates follow a **"no optimistic lie"** policy: spinners display until the server responds with confirmed status.

---

## 2. Connecting DealWatch to ChatGPT

### Option A: Cloud Deployment (Render.com)
If you deployed DealWatch using Phase 10 Blueprint on Render:
1. Copy your deployed public HTTPS base URL:
   `https://<your-service-name>.onrender.com`
2. In ChatGPT (Developer Mode or Custom GPT configuration):
   - Choose **Add Actions** or **MCP Connectors**.
   - Set Server URL to: `https://<your-service-name>.onrender.com/mcp`
   - Authentication:
     - If `AUTH_REQUIRED=false` (demo mode): Select **None**.
     - If `AUTH_REQUIRED=true`: Select **OAuth 2.1** with authorization URL `https://<your-service-name>.onrender.com/oauth/authorize` and token URL `https://<your-service-name>.onrender.com/oauth/token`.

### Option B: Local Testing via Ngrok Tunnel
To test DealWatch running on your local machine with ChatGPT:
1. Start your local FastAPI server:
   ```bash
   uv run uvicorn app.main:app --port 8000
   ```
2. Start an HTTPS tunnel via ngrok:
   ```bash
   ngrok http 8000
   ```
3. Copy the forwarding HTTPS address (e.g., `https://a1b2-c3d4.ngrok-free.app`).
4. Register the MCP URL in ChatGPT:
   `https://a1b2-c3d4.ngrok-free.app/mcp`

---

## 3. The `window.openai` Bridge Specification

The widget communicates with the host ChatGPT interface using standard Apps SDK hooks:

### Receiving Data (`toolOutput`):
When the widget loads, it inspects `window.openai.toolOutput` for tool results:
```javascript
window.addEventListener('DOMContentLoaded', () => {
  if (window.openai && window.openai.toolOutput) {
    render(window.openai.toolOutput);
  }
});
```

### Triggering Tool Calls (`callTool`):
Interactive buttons invoke server tools asynchronously:
```javascript
// Start 14-day price tracking
const res = await window.openai.callTool("track_subject", {
  subject_id: currentData.subject_id,
  offer_ids: offerIds,
  target_price: targetVal ? parseFloat(targetVal) : null,
  price_drop_alert: true,
  duration_days: 14
});

// Stop price tracking
const res = await window.openai.callTool("stop_tracking", {
  tracker_id: trackerId
});
```

---

## 4. Standalone Preview & CSP Safety

The widget ([`app/ui/dealwatch_widget.html`](file:///Users/samarthsingh/Desktop/Programs/compare/app/ui/dealwatch_widget.html)) is built with 100% inline CSS and vanilla JavaScript:
- **No External CDNs**: Works cleanly under the strictest Content Security Policies (`script-src 'self'`, `style-src 'unsafe-inline'`).
- **Dark/Light Mode Adaptation**: Automatically conforms to ChatGPT's color scheme via `prefers-color-scheme`.
- **Standalone Mode**: If opened directly in a browser (e.g. `open app/ui/dealwatch_widget.html`), it automatically hydrates with a rich demo dataset and simulates interactive button calls for testing.

---

## 5. Verification Commands

Run the automated test suite for the UI resource and ChatGPT metadata:

```bash
# Run ChatGPT widget unit & integration tests
uv run pytest tests/test_chatgpt_widget.py -v

# Verify MCP server resource endpoints
uv run pytest tests/test_mcp_server.py -k "test_mcp_streamable_http_initialization or test_mcp_registered_tools_catalog" -v
```
