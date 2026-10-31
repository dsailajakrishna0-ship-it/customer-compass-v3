# Architecture decision records (ADRs)

One short file per decision, so the reason for a choice is not buried in a long stage document.

- Name files `NNNN-short-title.md`, numbered in order. Never reuse a number; supersede instead.
- Use the template below. Keep it to one page.
- Every tool adopted or rejected in V3 gets an ADR with the **pinned version** and a link to the eval or test that justified it (see [roadmap.md](../roadmap.md)).

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-v3-goals-and-tooling-rule.md) | V3 goals and tooling rule | Accepted |
| [0002](0002-developer-tooling.md) | Developer tooling | Accepted |
| [0003](0003-ci-and-supply-chain-checks.md) | CI and supply-chain checks | Accepted |
| [0004](0004-release-and-image-publishing.md) | Release and image publishing | Accepted |
| [0005](0005-database-migrations.md) | Database migrations | Accepted |
| [0006](0006-evaluation-baseline.md) | Evaluation baseline | Accepted |
| [0007](0007-documentation-track.md) | Documentation track | Accepted |
| [0008](0008-config-and-logging.md) | Settings, model catalogue and structured logging | Accepted |
| [0009](0009-litellm-gateway.md) | The model gateway (LiteLLM) | Accepted |
| [0010](0010-cloud-only-models.md) | Cloud-only chat models | Accepted |
| [0011](0011-streaming-deferred.md) | Streaming answers (SSE): deferred | Accepted |
| [0012](0012-agent-limits.md) | Agent limits (steps and time) | Accepted (numbers pending) |
| [0013](0013-conflict-bot.md) | A conflict-resolving helper (Phase 1: a script run by hand) | Accepted |
| [0014](0014-native-tool-calling.md) | Native tool calling with Pydantic schemas | Accepted |
| [0015](0015-mcp-over-http-two-servers.md) | MCP over HTTP, with two interchangeable tool servers | Accepted |
| [0016](0016-spring-boot-mcp-server.md) | The Spring Boot MCP server | Accepted |
| [0017](0017-contract-and-internal-tests.md) | API-contract tests and internal tests | Accepted |

## Template

```markdown
# NNNN — Title

- **Status:** Proposed | Accepted | Superseded by NNNN
- **Date:** YYYY-MM-DD
- **Roadmap sub-stage:** e.g. 1.2

## Context
What problem or choice, and which constraints apply.

## Decision
What we chose (with pinned version).

## Alternatives considered
Short list, with why each was not chosen.

## Consequences
What gets easier, what gets harder, what to re-check later.
```
