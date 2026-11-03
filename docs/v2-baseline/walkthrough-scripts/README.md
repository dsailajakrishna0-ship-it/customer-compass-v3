# Walkthrough scripts

Three small scripts that run the **real V2 code** (the `customer-compass-v2` repository, tag `v2-final`) with a scripted model, and print what really happens. They produced the transcripts in [`../code-walkthrough.md`](../code-walkthrough.md). They change nothing in the V2 repository and do not need Ollama or any API key.

## Setup (once)

A Postgres with the demo CRM data. The simplest way is a throwaway container plus this repository's migrations:

```bash
docker run -d --rm --name cc-walkthrough-db -e POSTGRES_PASSWORD=customer_compass_dev \
  -e POSTGRES_USER=customer_compass -e POSTGRES_DB=customer_compass -p 55432:5432 postgres:17.11
cd customer-compass-v3/apps/api-py
DATABASE_URL=postgresql://customer_compass:customer_compass_dev@localhost:55432/customer_compass uv run alembic upgrade head
```

(The V3 migrations were derived from V2's `db/` SQL; the demo companies and interactions are the ones V2 seeds.) Stop it afterwards with `docker rm -f cc-walkthrough-db`.

## Run

From the **V2** repository, with V2's own virtualenv (it has the `mcp` library V2 used):

```bash
cd customer-compass-v2/apps/api-py
export DATABASE_URL=postgresql://customer_compass:customer_compass_dev@localhost:55432/customer_compass
S=../../../customer-compass-v3/docs/v2-baseline/walkthrough-scripts
PYTHONPATH=. ./.venv/bin/python $S/01_mcp_wire.py            # the raw MCP messages
PYTHONPATH=. ./.venv/bin/python $S/02_tool_calling_loop.py   # what the model is sent on each loop round
PYTHONPATH=. ./.venv/bin/python $S/03_agent_workflow.py      # what each agent receives, and the trace
```

Log lines from the application start with `{"event"` and can be hidden with `| grep -vE '^\{"(event|status)"'`.

## What is real and what is scripted

| Real | Scripted |
| --- | --- |
| The MCP server and client (a real subprocess), the tools, the SQL, the guardrails, the agents' parsers, the workflow, the limits, the trace | The model's replies (a fixed list per script), and document retrieval in script 03 (one canned chunk instead of embeddings and the vector store) |
