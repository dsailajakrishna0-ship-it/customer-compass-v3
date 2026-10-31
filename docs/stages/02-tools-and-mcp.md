# Stage 2 — Tools and MCP: letting the model do things safely

> **Level:** beginner friendly; read [Stage 1](01-model-layer.md) first (the gateway). **Reading time:** about 20 minutes for what is written so far.
> **Status:** in progress. **2.1 and 2.2a (🟦MCP over HTTP, 🟦FastMCP) are written; 2.2b (Spring Boot) is added when it is built.**
> **Roadmap:** [Stage 2](../roadmap.md#stage-2--tools-and-mcp) · **Decisions:** [ADR 0014](../adr/0014-native-tool-calling.md), [ADR 0015](../adr/0015-mcp-over-http-two-servers.md)

**AI colour code:** 🟪 concept · 🟦 framework or tool · 🟩 data store or service · 🟧 model. Unmarked technical terms are ordinary software. [A to Z list](../ai-terms.md)

## In one minute

A 🟪language model only produces text. To look up a company's open deals or propose a follow-up task, it has to *ask* the application to do that, and the application has to decide whether to obey. Think of a restaurant: the customer (model) cannot walk into the kitchen; they hand an order slip to a waiter (our code), who checks the slip makes sense before the kitchen cooks anything.

| Restaurant idea | Project idea | What we built |
| --- | --- | --- |
| A printed menu with the exact fields on an order slip | **Tool schemas** (Pydantic models) | `app/mcp/schemas.py`: one model per tool |
| A standard slip format every waiter understands | **Native 🟪tool calling** | The model answers with a structured request, not special text |
| The waiter checks the slip before it goes to the kitchen | **Validation** | Wrong, extra or unknown fields come back to the model as an error message |
| "Only the manager can approve a refund" | **Confirmation decided by the user's message, not the model** | The model is not even offered a `confirm` field |
| The waiter stops after a few trips | **A bounded loop** | At most 4 rounds, at most 4 tools per reply |
| Two kitchens that cook the same menu; the customer picks one | **Two tool servers, one contract** (2.2a, 2.2b) | 🟦FastMCP (Python) and Spring Boot (Java), radio buttons in the web app, one checked contract |

## The big picture (2.1)

![One round of the tool loop: the user asks, the chat route sends messages and tool definitions through the gateway to the model; the model asks for a tool; the route validates the arguments against the Pydantic schema and either runs the tool on the MCP server or turns the problem into an error result; the result goes back to the model with the same call id, and the model writes the final answer.](../img/diagrams/stage2-tool-loop.png)

<sub>Diagram source: [stage2-tool-loop.mmd](../diagrams/stage2-tool-loop.mmd)</sub>

---

## Concept 1 — Native tool calling

**The problem.** The model must be able to say "run `get_open_deals` for Acme" in a form the program can read without guessing.

**V2's answer** was to teach the model a text format: reply with a fenced block containing JSON, and the route finds it with a regular expression. That was a workaround for a small local model that could not do better, and it had costs: one stray character wasted a whole turn, and the list of tools and their arguments lived in 🟪prompt prose.

**The idea.** Providers support 🟪tool calling directly. You send, next to the messages, a list of **function definitions** (a name, a description and a JSON Schema for the arguments). The model replies *either* with text *or* with a structured list of **🟪tool calls**: an id, a name and the arguments as JSON text. You run them and send the results back as `tool` messages carrying the same ids. Our gateway ([Stage 1](01-model-layer.md#concept-4--calling-models-safely-the-model-gateway)) sends this through 🟦LiteLLM, so every model in the fallback chain is asked the same way.

A worked example from the demo data. The user asks "What are Acme Fabrication's open deals?":

```text
model  -> tool call  id=call_0  get_open_deals  {"company_name": "Acme Fabrication"}
route  -> tool message  tool_call_id=call_0  (the deals, wrapped as untrusted data)
model  -> "Acme Fabrication has one open deal: ..."
```

Three rules make it safe to loop:

1. **Every requested call gets an answer.** Providers reject a conversation where an assistant tool call has no matching `tool` message, so even refused calls get one (an error text).
2. **It is bounded.** At most 4 rounds and 4 tool calls per reply. If the model is still asking after round 4, one last reply is forced to be text (`tool_choice="none"`).
3. **Tool output is data.** Results are scanned for injection and wrapped in `<untrusted_context>` tags, as before.

> [!NOTE]
> **What we have not seen.** No 🟩OpenRouter key was available, so no free model has been observed making a tool call through this code. Free models differ in how well they support tool calling. The tests use a scripted model; the real behaviour is checked when the `tools` evaluation is re-taken with a key (see [ADR 0014](../adr/0014-native-tool-calling.md)).

## Concept 2 — Schemas that define *and* validate

**The problem.** The model's arguments are untrusted input, exactly like a web form. A model can leave out a field, send the wrong type, invent an argument, or ask for a tool that does not exist.

**The idea.** One Pydantic model per tool is both the schema the model sees and the check on what it sends:

```python
class TaskArgs(_Args):
    company_name: str = Field(min_length=1, description="The company the follow-up is for.")
    note: str = Field(min_length=1, max_length=500, description="What the follow-up task is.")
```

`model_json_schema()` produces the `parameters` shown to the model; `model_validate()` checks what comes back. `extra="forbid"` means an argument the schema does not name is an error. A bad call is **not** an exception: it becomes an error result (`Invalid arguments for create_followup_task: confirm: Extra inputs are not permitted`) that the model can read and correct on its next turn.

### The design choice that matters most: who confirms?

Creating a task is the one action with side effects. The rule is that a task is created only when the **user's own latest message** confirms it. In V2 the route overwrote the `confirm` argument after the model had sent it. Now `confirm` is not in the model's schema at all: a model that sends it gets an error and nothing runs. The route sets it from the user's message.

| | V2 | V3 (2.1) |
| --- | --- | --- |
| Can the model send `confirm`? | Yes, then it was overwritten | No: not in the schema, and rejected if sent |
| Tool list and arguments | In 🟪prompt prose | In the request, from Pydantic models |
| Finding the call | A regular expression on the reply | A structured field of the reply |
| A malformed call | Lost a turn | Becomes an error result the model can fix |
| Unknown tool | Passed to the server | Refused before the server |

### Keeping the two lists in step

The tool server (`app/mcp/server.py`) and the models in `schemas.py` must agree. A tool without a model is never offered to the model, and a test fails if the server offers a tool that has none, so a new tool cannot be added half-way.

### Lessons

> [!IMPORTANT]
> 1. **Treat model output as untrusted input.** Validate arguments the way you would validate a form.
> 2. **Do not offer a model a control it must not use.** Leaving `confirm` out of the schema beats overwriting it afterwards.
> 3. **Turn failures into messages, not crashes.** A model can fix a clear error; an exception ends the turn.
> 4. **Say what was not observed.** The loop is tested against a scripted model, not a real one.

---

## Concept 3 — A tool server as a service, and two interchangeable ones (2.2a)

**The problem.** In V2 and in 2.1, every tool-calling question started a new Python process, talked to it over standard input and output (🟦MCP "stdio"), and threw it away. That costs a process start per question and keeps the tools locked inside the API.

**The idea.** MCP also has an HTTP transport (**streamable HTTP**). The tool server becomes a normal, long-running service with an address; the API connects to it, asks for its tools, calls them and disconnects. Because it is "just an address", a second implementation can listen at another address and the API can talk to either.

![The web app's radio buttons send mcpServer with the chat request; the API's registry picks the URL; the FastMCP server in Python on port 8002 reads Postgres and Qdrant. A Spring Boot server on port 8003 (Stage 2.2b) is drawn as a later, dashed box. A shared contract file is checked against both.](../img/diagrams/stage2-mcp-topology.png)

<sub>Diagram source: [stage2-mcp-topology.mmd](../diagrams/stage2-mcp-topology.mmd)</sub>

### Choosing a server: one setting, one request field, two radio buttons

| Where | What | Example |
| --- | --- | --- |
| Environment | The default server | `MCP_BACKEND=fastmcp` |
| Environment | Each server's address; empty means "not configured" | `MCP_SPRINGBOOT_URL=http://mcp-spring:8003/mcp` |
| One chat request | Overrides the default | `{"messages": [...], "mcpServer": "springboot"}` |
| Web app | Radio buttons under the chat mode, shown in tool-calling mode | An unconfigured server is greyed out with "(not configured)" |

A request for a server that does not exist or is not configured is a clear `400` that names the setting to change, not a failure halfway through a conversation. `GET /api/v1/mcp/servers` lists each server with whether it is configured and whether it answers right now.

### One contract, so "interchangeable" is checked

Two servers can quietly drift apart. The file `contracts/mcp-tools.json` says what *every* server must offer: the four tools with their argument names, types and required fields, plus a few read-only calls with the answers expected on the demo data, for example `get_open_deals("Acme")` must return `Premium Operations Plan renewal`. `contracts/check_server.py` runs that check against any running server:

```text
$ just mcp-contract http://localhost:8002/mcp
http://localhost:8002/mcp: OK (4 cases)
```

CI runs it on the real FastMCP container. The Spring Boot server (2.2b) has to pass the same check. The file sits at the repository root because it belongs to neither server.

### A trap we met: the error that said nothing

With no 🟩OpenRouter key the tools route answered *"unhandled errors in a TaskGroup (1 sub-exception)"*. The MCP session runs inside an async task group, which wraps any error that escapes it in an exception group with that unhelpful message. The route now unwraps it, so the user sees the real "set `OPENROUTER_API_KEY`" message again. We found this by running the real stack, not by the unit tests, which is why the stack was run.

### The Host check

The server accepts only requests whose `Host` header is in `MCP_ALLOWED_HOSTS` (`localhost`, `127.0.0.1`, `mcp-fastmcp`). This stops a web page from tricking a browser into talking to a local server under another name ("DNS rebinding"). A request with an unknown host gets `421`.

### Lessons

> [!IMPORTANT]
> 1. **A service has an address.** Moving from "start a process" to "call an address" is what makes a second implementation possible.
> 2. **Interchangeable needs a checker.** Say what both must do in one file, and test both against it.
> 3. **Make "not available" a visible state.** A greyed-out option with a reason beats a failure later.
> 4. **Run the real thing.** The most useful bug of this sub-stage appeared only in the running stack.

> [!NOTE]
> **What we have not seen.** A real chat turn through the tool servers needs an OpenRouter key and none was available. The server, the HTTP client, the contract check, the Compose wiring and the error cases were run for real; the model's side was not.

---

## Code tour: what changed in 2.2a, and why

Bright green is new in this sub-stage (2.2a), amber is an existing module that changed in it, grey is existing and untouched (Stages 0 to 2.1 are collapsed to one grey box). Markers in the tables: 🟢 new, 🟡 changed, ⚪ earlier.

![Module map after sub-stage 2.2a: the web chat panel and a new server picker call the chat route and a new GET /mcp/servers route. Both use a new registry that reads the MCP settings in config.py. The client now makes an HTTP session to the FastMCP server instead of starting a subprocess. A new contracts folder and three new test files check the server. Earlier modules are collapsed into one grey box.](../img/diagrams/stage2-module-map.png)

<sub>Diagram source: [stage2-module-map.mmd](../diagrams/stage2-module-map.mmd)</sub>

### New files

| | Added in | File | What it is for | Names to look at | Used by |
| --- | --- | --- | --- | --- | --- |
| 🟢 | 2.2a | [`app/mcp/registry.py`](../../apps/api-py/app/mcp/registry.py) | Which backend, which URL; refuses unknown or unconfigured ones | `resolve()`, `backends()`, `UnknownBackendError` | `client.py`, `routes/chat.py`, `routes/mcp.py` |
| 🟢 | 2.2a | [`app/routes/mcp.py`](../../apps/api-py/app/routes/mcp.py) | `GET /api/v1/mcp/servers`: configured and reachable | `servers()`, `_reachable()` | The web app |
| 🟢 | 2.2a | [`contracts/mcp-tools.json`](../../contracts/mcp-tools.json), [`check_server.py`](../../contracts/check_server.py), [`README.md`](../../contracts/README.md) | The shared tool contract and the checker for any server | `compare_tools()`, `check_case()` | CI, `just mcp-contract`, both servers |
| 🟢 | 2.2a | `apps/web/src/components/chat/McpServerPicker.tsx`, `mcpServerStatus.ts`, `hooks/useMcpServers.ts`, `api/mcp.ts` | The radio buttons and their data | `McpServerPicker`, `unavailableReason()` | `ChatModeSelector.tsx` |
| 🟢 | 2.2a | `tests/test_mcp_http.py`, `test_mcp_registry.py`, `test_mcp_contract.py`; `McpServerPicker.test.tsx` | Real HTTP round trip, backend choice, contract, picker | `running_server` | CI |
| 🟢 | 2.2a | [ADR 0015](../adr/0015-mcp-over-http-two-servers.md) | The decision and what is not verified | | Readers |
| ⚪ | 2.1 | [`app/mcp/schemas.py`](../../apps/api-py/app/mcp/schemas.py), `tests/test_chat_tools.py`, `test_tool_schemas.py` | What the model may pass to each tool | `TOOL_ARGS` | Both |

### Existing files that changed, and what changed

| | Changed in | File | Change |
| --- | --- | --- | --- |
| 🟡 | 2.2a | `app/mcp/server.py` | Runs over streamable HTTP as its own service; Host allowlist |
| 🟡 | 2.2a | `app/mcp/client.py` | An HTTP session to the chosen server; the stdio subprocess is gone |
| 🟡 | 2.2a | `app/config.py` | `MCP_*` settings; `subprocess_env()` removed (nothing needs it now) |
| 🟡 | 2.2a | `app/routes/chat.py` | `mcpServer` request field, `400` for a bad choice, `mcpServer` in the answer, real error shown instead of the task-group message |
| 🟡 | 2.2a | `docker-compose.yml`, `.github/workflows/ci.yml`, `.env.example`, `justfile` | The `mcp-fastmcp` service; CI checks the API reaches it and runs the contract; settings; `just mcp-contract` |
| 🟡 | 2.2a | Web: `ChatModeSelector`, `ChatPanel`, `ChatSessionContext`, `useChat`, `MessageBubble`, types, CSS | The radio buttons, the stored choice, the request field, "via fastmcp" in the tool trail |
| 🟡 | 2.2a | `docs/` | API reference, architecture, tech stack, roadmap |
| ⚪ | 2.1 | `routes/chat.py` loop, `gateway.py`, `types.py` | Native 🟪tool calling (see above) |

### A good reading order

1. **`contracts/mcp-tools.json`**: the whole promise, in 60 lines of data.
2. **`app/mcp/registry.py`**: how a name becomes an address, and how it refuses.
3. **`app/mcp/client.py`**: compare it with the version before (stdio): the diff is the story of this sub-stage.
4. **`tests/test_mcp_http.py`**: a real server and a real client in one test.
5. **`McpServerPicker.tsx`**: the same idea, in the browser.

## What this stage added to the tech stack (so far)

| Tool | What it does in plain words | Where to look |
| --- | --- | --- |
| **Pydantic** (already used) | Describes the shape of data, checks it, and produces JSON Schema | `apps/api-py/app/mcp/schemas.py` |
| **🟪Tool calling** (provider feature, through 🟦LiteLLM) | The model asks for a function by name with JSON arguments | `app/llm/gateway.py` |
| **🟦FastMCP** (the `MCPServer` of the official `mcp` SDK, 2.2a) | A long-running tool server that speaks MCP over HTTP | `apps/api-py/app/mcp/server.py` |
| **Streamable HTTP** (MCP transport, 2.2a) | How the API and a tool server talk over the network | `apps/api-py/app/mcp/client.py` |

## V2 vs V3 in this area

| | V2 | V3 (2.1) | Why it changed |
| --- | --- | --- | --- |
| How a call is signalled | A fenced text block in the reply, found with a regular expression | The provider's structured tool-call field | The small local model that needed the workaround is gone |
| Arguments | Whatever JSON the model wrote | Validated against a Pydantic model | Model output is untrusted input |
| `confirm` | Overwritten after the model sent it | Not in the schema; rejected if sent | A control the model must not use should not be offered |
| Bad calls | Cost a turn | An error result the model can correct | Models recover from clear errors |
| Tool server | A new subprocess (stdio) for every chat turn | A long-running service over HTTP (2.2a) | Shareable, observable, and a second implementation can be swapped in |

## Glossary

- **Function definition**: the description of a tool given to the model: name, purpose and a JSON Schema for the arguments.
- **Contract (here)**: a file that says what every implementation of a service must do, checked automatically against each one.
- **DNS rebinding**: a trick that makes a browser send requests to a local server under another host name; a Host allowlist stops it.
- **JSON Schema**: a standard way to describe the shape of JSON data (which fields, which types, which are required).
- **Long-lived service**: a program that keeps running and answers many requests, as opposed to one started for each request.
- **Pydantic**: a Python library that describes data shapes, validates them and can export JSON Schema.
- **Streamable HTTP**: the 🟦MCP transport that carries requests and answers over ordinary HTTP, so a tool server can be a separate service.
- **🟪Tool call**: the model's request to run a named function with given arguments; it has an id so the result can be matched to it.
- **Tool message**: the reply we send back for one tool call, carrying that call's id.
- **Validation**: checking that input has the shape and limits you expect before using it.
- **Untrusted input**: anything not written by us (users, web pages, and the model's own output) that must be checked before it can cause an effect.

## Check your understanding

<details><summary>1. Why did V2 use a fenced text block, and why is it gone?</summary>

It was a workaround for a small local model that could not produce structured 🟪tool calls. The local model was removed in Stage 1.3, so the workaround had no reason left, and native calling removes its weaknesses (a stray character costing a turn, tool lists in 🟪prompt prose).
</details>

<details><summary>2. A model replies with three tool calls at once. What must the route send back, and why?</summary>

One `tool` message per call, each with the matching call id. Providers reject a conversation in which an assistant tool call has no matching tool message.
</details>

<details><summary>3. Why is <code>confirm</code> not in the schema shown to the model?</summary>

Creating a task is the one side-effecting action, and it may happen only when the user's own latest message confirms it. A control the model must not use should not be offered at all; if it sends one anyway, it gets an error and nothing runs.
</details>

<details><summary>4. The model sends invalid arguments. What happens, and why not raise an error?</summary>

The route returns the validation message as the tool's result, and nothing runs. The model can read it and correct itself on its next turn; an exception would end the whole request.
</details>

<details><summary>5. What stops the tool loop running forever?</summary>

At most 4 rounds and at most 4 tool calls per reply. After the last round, one more reply is requested with <code>tool_choice="none"</code>, which forces plain text.
</details>

<details><summary>6. What could not be verified in this sub-stage?</summary>

No free model has been seen making a tool call through this code, because no 🟩OpenRouter key was available. The loop is tested with a scripted model and a fake tool server; the `tools` evaluation must be re-taken with a key to measure real behaviour.
</details>

<details><summary>7. What does a long-lived tool server give you that a subprocess per question did not?</summary>

No process start per question, an address other programs can use, and the freedom to run, watch and replace it on its own. It is also what makes a second implementation possible: the API only needs a different address.
</details>

<details><summary>8. A request names <code>mcpServer: "springboot"</code> but that server is not configured. What happens?</summary>

A `400` that names the setting to change (`MCP_SPRINGBOOT_URL`), before any model call. The web app also greys that radio button out with "(not configured)".
</details>

<details><summary>9. How do we know two tool servers are really interchangeable?</summary>

`contracts/mcp-tools.json` says what both must offer and answer, and `check_server.py` runs it against a running server. CI runs it on the 🟦FastMCP container; the Java server must pass the same check.
</details>

<details><summary>10. Why does the contract live at the repository root instead of inside the Python or Java folder?</summary>

It belongs to neither implementation. Putting it under one would make the other look like a copy, and it would be easy to change one side without the other noticing.
</details>

<details><summary>11. With no OpenRouter key, the tools route once answered "unhandled errors in a TaskGroup". What was wrong?</summary>

The MCP session runs in an async task group, which wraps any error that escapes in an exception group with that useless message. The route now unwraps it to the real error. Unit tests could not show it; running the real stack did.
</details>

## Further reading

- OpenAI 🟪function calling guide (the format 🟦LiteLLM follows): <https://platform.openai.com/docs/guides/function-calling>
- LiteLLM, function calling: <https://docs.litellm.ai/docs/completion/function_call>
- Pydantic, JSON Schema: <https://docs.pydantic.dev/latest/concepts/json_schema/>
- 🟦Model Context Protocol: <https://modelcontextprotocol.io/>
