> **Archived.** This is a frozen snapshot of the original flat 8-stage numbering
> (Stages 1–8), kept for history. The living roadmap now lives in `docs/README.md`,
> reorganized into Parts I–IV with additional stages. See `docs/README.md` for
> the current index.

# Customer Compass development guide

This folder is the durable engineering record for the learning project. Read the
stage documents in order; each stage has a working boundary and must be verified
before the next stage changes its assumptions.

| Stage | Status | Document |
| --- | --- | --- |
| 1. CRM foundation | Complete | [01-foundation.md](01-foundation.md) |
| 2. Local LLM chat | Complete | [02-first-llm-chat.md](02-first-llm-chat.md) |
| 3. Basic RAG | Planned | [03-basic-rag.md](03-basic-rag.md) |
| 4. CRM RAG | Planned | [04-realistic-crm-rag.md](04-realistic-crm-rag.md) |
| 5. Retrieval evaluation | Planned | [05-retrieval-evaluation.md](05-retrieval-evaluation.md) |
| 6. Production concerns | Planned | [06-production-concerns.md](06-production-concerns.md) |
| 7. Tool calling | Planned | [07-tool-calling.md](07-tool-calling.md) |
| 8. Agentic assistant | Planned | [08-agentic-assistant.md](08-agentic-assistant.md) |

## Baseline stack

- Frontend: React + Vite + TypeScript
- Backend: Express + TypeScript
- Relational data: PostgreSQL 17 in Docker
- Local inference: Ollama + Qwen2.5 3B in Docker

This is an intentionally small, original CRM. It uses only synthetic data and
does not reproduce an existing CRM product.

See [conversation-progress.md](conversation-progress.md) for a concise running
record of decisions, completed work, environment setup, and the next stage.

## Developer note

This documentation increment adds `docs/README.md` and the eight numbered stage
documents. Keep this index updated whenever a stage changes from Planned to
Complete or its implementation scope changes.
