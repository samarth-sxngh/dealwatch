"""DealWatch Deployment Smoke Test CLI.

Validates a local or remote live deployment of DealWatch:
1. Liveness probe: GET /health
2. Readiness probe: GET /ready (database connectivity)
3. OAuth 2.1 RFC 9728 metadata: GET /.well-known/oauth-protected-resource
4. OAuth 2.1 RFC 8414 metadata: GET /.well-known/oauth-authorization-server
5. Streamable HTTP MCP Handshake: POST /mcp with JSON-RPC initialize

Usage:
    python -m scripts.smoke_test --url https://dealwatch.onrender.com
    python -m scripts.smoke_test --url http://127.0.0.1:8000 --token "<optional-jwt>"
"""

import argparse
import asyncio
import sys
from typing import Any

import httpx


async def run_smoke_tests(base_url: str, token: str | None = None, timeout: float = 30.0) -> bool:
    """Runs all deployment smoke tests against target base_url.

    Returns True if all critical tests pass, False otherwise.
    """
    base = base_url.rstrip("/")
    print(f"\n🔍 Running DealWatch Deployment Smoke Test against: {base}\n" + "=" * 70)

    auth_headers = {}
    if token:
        auth_headers["Authorization"] = f"Bearer {token}"

    all_passed = True
    results: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        # ----------------------------------------------------------------------
        # 1. Liveness Probe (/health)
        # ----------------------------------------------------------------------
        try:
            res = await client.get(f"{base}/health")
            if res.status_code == 200 and res.json().get("status") == "ok":
                results.append(
                    {"name": "1. Liveness (/health)", "status": "PASS", "details": res.json()}
                )
            else:
                results.append(
                    {
                        "name": "1. Liveness (/health)",
                        "status": "FAIL",
                        "details": f"HTTP {res.status_code}: {res.text}",
                    }
                )
                all_passed = False
        except Exception as e:  # noqa: BLE001
            results.append(
                {
                    "name": "1. Liveness (/health)",
                    "status": "FAIL",
                    "details": f"Connection error: {e}",
                }
            )
            all_passed = False

        # ----------------------------------------------------------------------
        # 2. Readiness Probe (/ready)
        # ----------------------------------------------------------------------
        try:
            res = await client.get(f"{base}/ready")
            if res.status_code == 200 and res.json().get("database") == "connected":
                results.append(
                    {"name": "2. Readiness (/ready)", "status": "PASS", "details": res.json()}
                )
            else:
                results.append(
                    {
                        "name": "2. Readiness (/ready)",
                        "status": "FAIL",
                        "details": f"HTTP {res.status_code}: {res.text}",
                    }
                )
                all_passed = False
        except Exception as e:  # noqa: BLE001
            results.append(
                {
                    "name": "2. Readiness (/ready)",
                    "status": "FAIL",
                    "details": f"Connection error: {e}",
                }
            )
            all_passed = False

        # ----------------------------------------------------------------------
        # 3. OAuth Protected Resource Metadata (RFC 9728)
        # ----------------------------------------------------------------------
        try:
            res = await client.get(f"{base}/.well-known/oauth-protected-resource")
            if res.status_code == 200:
                data = res.json()
                results.append(
                    {
                        "name": "3. RFC 9728 Protected Resource",
                        "status": "PASS",
                        "details": f"Resource: {data.get('resource')}, Scopes: {data.get('scopes_supported')}",
                    }
                )
            else:
                results.append(
                    {
                        "name": "3. RFC 9728 Protected Resource",
                        "status": "FAIL",
                        "details": f"HTTP {res.status_code}",
                    }
                )
                all_passed = False
        except Exception as e:  # noqa: BLE001
            results.append(
                {"name": "3. RFC 9728 Protected Resource", "status": "FAIL", "details": str(e)}
            )
            all_passed = False

        # ----------------------------------------------------------------------
        # 4. OAuth Authorization Server Metadata (RFC 8414)
        # ----------------------------------------------------------------------
        try:
            res = await client.get(f"{base}/.well-known/oauth-authorization-server")
            if res.status_code == 200:
                results.append(
                    {
                        "name": "4. RFC 8414 Auth Server",
                        "status": "PASS",
                        "details": f"Issuer: {res.json().get('issuer')}",
                    }
                )
            elif res.status_code == 404:
                results.append(
                    {
                        "name": "4. RFC 8414 Auth Server",
                        "status": "INFO",
                        "details": "Not configured / handled by external IdP (expected if using direct IdP issuer)",
                    }
                )
            else:
                results.append(
                    {
                        "name": "4. RFC 8414 Auth Server",
                        "status": "FAIL",
                        "details": f"HTTP {res.status_code}",
                    }
                )
                all_passed = False
        except Exception as e:  # noqa: BLE001
            results.append({"name": "4. RFC 8414 Auth Server", "status": "FAIL", "details": str(e)})
            all_passed = False

        # ----------------------------------------------------------------------
        # 5. MCP Streamable HTTP Handshake (/mcp)
        # ----------------------------------------------------------------------
        try:
            mcp_headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                **auth_headers,
            }
            init_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "dealwatch-smoke-test", "version": "1.0.0"},
                },
            }
            res = await client.post(f"{base}/mcp", json=init_payload, headers=mcp_headers)
            if res.status_code == 200 and ("DealWatch" in res.text or "capabilities" in res.text):
                results.append(
                    {
                        "name": "5. MCP Streamable HTTP (/mcp)",
                        "status": "PASS",
                        "details": f"HTTP 200 OK | Content-Type: {res.headers.get('content-type', 'unknown')}",
                    }
                )
            elif res.status_code == 401:
                # If AUTH_REQUIRED is true and no token was provided, 401 is expected behavior for protected MCP
                if not token:
                    results.append(
                        {
                            "name": "5. MCP Streamable HTTP (/mcp)",
                            "status": "PASS (AUTH ENFORCED)",
                            "details": "HTTP 401 Unauthorized (Auth is required and working; provide --token to test handshake)",
                        }
                    )
                else:
                    results.append(
                        {
                            "name": "5. MCP Streamable HTTP (/mcp)",
                            "status": "FAIL",
                            "details": "HTTP 401 Unauthorized with provided token",
                        }
                    )
                    all_passed = False
            else:
                results.append(
                    {
                        "name": "5. MCP Streamable HTTP (/mcp)",
                        "status": "FAIL",
                        "details": f"HTTP {res.status_code}: {res.text[:200]}",
                    }
                )
                all_passed = False
        except Exception as e:  # noqa: BLE001
            results.append(
                {"name": "5. MCP Streamable HTTP (/mcp)", "status": "FAIL", "details": str(e)}
            )
            all_passed = False

    # --------------------------------------------------------------------------
    # Output Summary Table
    # --------------------------------------------------------------------------
    for r in results:
        status_tag = f"[{r['status']}]"
        print(f"{status_tag:<22} {r['name']}")
        print(f"   ↳ {r['details']}\n")

    print("=" * 70)
    if all_passed:
        print("✅ ALL CRITICAL SMOKE CHECKS PASSED: Live deployment is healthy & MCP ready!\n")
    else:
        print("❌ ONE OR MORE SMOKE CHECKS FAILED: Review the details above.\n")

    return all_passed


def main() -> None:
    parser = argparse.ArgumentParser(description="DealWatch Deployment Smoke Test")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000",
        help="Base URL of deployed service (e.g. https://dealwatch.onrender.com)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional JWT Bearer token if testing against an auth-protected deployment",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds (useful for cold starts, default: 30.0)",
    )
    args = parser.parse_args()

    success = asyncio.run(
        run_smoke_tests(base_url=args.url, token=args.token, timeout=args.timeout)
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
