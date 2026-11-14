# Stage E3: a supervisor with specialist agents (Python extension)

The Python twin of the Java edition's E3 (see [python-extensions.md](../python-extensions.md)). Decisions: [ADR 0033](../adr/0033-supervisor-with-specialist-agents.md). Cut into slices: **E3.1** the supervisor graph (this page), **E3.2** an answer team and the supervisor's own search words, **E3.3** a comparison with the fixed pipeline.

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](../ai-terms.md)

## E3.1: `POST /api/v1/agent/supervise`

```mermaid
flowchart TD
  start(["request (guarded)"]) --> sup{"supervisor<br/>decides the next specialist"}
  sup -->|crm_facts| crm["crm_facts<br/>customer, deals, interactions"]
  sup -->|researcher| res["researcher<br/>every knowledge base"]
  sup -->|analyst| ana["analyst"]
  sup -->|reviewer| rev["reviewer<br/>+ two code rules"]
  sup -->|drafter| dra["drafter<br/>+ output guard"]
  crm --> sup
  res --> sup
  ana --> sup
  rev --> sup
  dra --> sup
  sup -->|FINISH| gate(["approval gate<br/>POST /agent/confirm"])
  sup -.->|"no customer found"| stop(["company_not_found"])
```

| Piece | File | Job |
| --- | --- | --- |
| The graph, the rules, the specialists | `app/agent/supervisor.py` | supervisor node, `allowed()`, the five specialists |
| The route | `app/routes/supervise.py` | `POST /agent/supervise`, same request and errors as `/agent/recommend` |
| The setting | `app/config.py` | `SUPERVISOR_MAX_TURNS` (default 10) |
| Reused | `app/agent/workflow.py` nodes, `agents.py`, the approval graph | the specialists' work, the guard, the pause |

### What the supervisor may do

Each turn code builds the list of **allowed** specialists; the model chooses from it only when there is more than one.

| State | Allowed |
| --- | --- |
| customer not loaded | `crm_facts` |
| no customer found | `FINISH` |
| no recommendation yet | `analyst`, and `researcher` (at most twice) |
| a recommendation, not reviewed | `reviewer` |
| reviewed and approved, or out of revisions | `drafter` |
| reviewed and sent back, revisions left | `analyst`, and `researcher` |
| note written | `FINISH` |

An unreadable or disallowed answer is replaced by the first allowed entry (the fixed pipeline's next step) and recorded with the reason.

### Concepts

1. **Pipeline versus supervisor.** A pipeline has the order in code; a supervisor has the order in a model's turn-by-turn decisions. The supervisor is more flexible and costs more (not measured here until E3.3).
2. **A model coordinating models needs rails.** The supervisor is itself a model, so preconditions, caps and limits are code, and a bad answer degrades to the pipeline instead of derailing the run.
3. **Hand control back.** Every specialist returns to the supervisor, so it sees the new state before choosing again. In 🟦LangGraph that is one edge from each specialist back to the supervisor node.
4. **Do not ask when there is no choice.** One allowed specialist means no model call.
5. **Specialists are reusable.** Four of the five are the account 🟪agent's own nodes; the fifth (the researcher) uses the multi-source search of E1. Adding a specialist is adding a node, a precondition and a line in the 🟪prompt.
6. **Decisions are data.** The response lists every turn: who chose (`supervisor` or `code`), why, what was allowed, and what the model proposed when it was overridden.
7. **State is versioned where it must be.** A review is of one recommendation: `rec_version` and `review_version` stop the drafter running on a review of an earlier proposal.
8. **The human gate stays.** However the work was coordinated, nothing is written until `POST /agent/confirm` with a yes.

### How to try E3.1

```bash
just up && just seed && just kb-ingest agri-supply     # the stack and both corpora (needs the embedding and chat keys)
just supervise "Analyze Acme Fabrication and recommend a next action"
```

Notice: `supervisor.turns` lists each decision. Most say `"source": "code"` and `"reason": "only one choice allowed"`; the turn before the analyst is the real choice (`"source": "supervisor"`), and it may have called the researcher first (look for `search_knowledge_bases` in `trace`). A name the CRM does not have (`Analyze Globex and recommend a next action`) ends at once as `company_not_found` with no model call. Nothing is written until `POST /agent/confirm` (the web app's Confirm button, or the curl in the testing guide).

## What comes next

**E3.2** adds an answer team for plain questions and lets the supervisor write its own search words; **E3.3** compares the supervisor with the fixed pipeline on the Java edition's ten golden cases, recorded once and replayable without keys.
