"""The raw MCP messages between a client and the V2 tool server (over stdio).

Part of docs/v2-baseline/code-walkthrough.md. Runs the REAL V2 code (the customer-compass-v2 repository,
tag v2-final) with a scripted stand-in for the model, so the output is the same every time and needs no
Ollama and no keys. It does need a Postgres with the demo data (see docs/v2-baseline/walkthrough-scripts/README.md).

Run from the V2 repository's apps/api-py folder, with V2's own virtualenv:

    cd ../customer-compass-v2/apps/api-py
    DATABASE_URL=postgresql://customer_compass:customer_compass_dev@localhost:55432/customer_compass \
      PYTHONPATH=. ./.venv/bin/python <path to this repo>/docs/v2-baseline/walkthrough-scripts/01_mcp_wire.py
"""

import json
import os
import subprocess
import sys

env = dict(os.environ)
env.setdefault(
    "DATABASE_URL",
    "postgresql://customer_compass:customer_compass_dev@localhost:55432/customer_compass",
)
p = subprocess.Popen(
    [sys.executable, "-m", "app.mcp.server"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
    env=env,
)


def send(msg, expect_reply=True):
    p.stdin.write(json.dumps(msg) + "\n")
    p.stdin.flush()
    if expect_reply:
        line = p.stdout.readline()
        return json.loads(line)


out = []
out.append(
    (
        "client -> server",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "demo", "version": "1"},
            },
        },
    )
)
out.append(("server -> client", send(out[-1][1])))
send({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)
out.append(("client -> server", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
out.append(("server -> client", send(out[-1][1])))
out.append(
    (
        "client -> server",
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_open_deals", "arguments": {"company_name": "Acme"}},
        },
    )
)
out.append(("server -> client", send(out[-1][1])))
p.stdin.close()
p.terminate()
for who, m in out:
    if who.startswith("server") and m.get("id") == 2:
        tools = m["result"]["tools"]
        m = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {k: t[k] for k in ("name", "description", "inputSchema") if k in t}
                    for t in tools[:2]
                ],
                "...": f"(2 of {len(tools)} tools shown)",
            },
        }
    print(f"--- {who}")
    print(json.dumps(m, indent=2)[:1500])
