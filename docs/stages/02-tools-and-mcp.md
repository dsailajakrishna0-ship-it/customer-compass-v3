# Stage 2 — Tools and MCP: letting the model do things safely

> **Level:** beginner friendly; read [Stage 1](01-model-layer.md) first (the gateway). **Reading time:** about 20 minutes for what is written so far.
> **Status:** in progress. **All of Stage 2 so far is written: 2.1 (native 🟪tool calling), 2.2a (🟦MCP over HTTP, 🟦FastMCP) and 2.2b (Spring Boot).**
> **Roadmap:** [Stage 2](../roadmap.md#stage-2--tools-and-mcp) · **Decisions:** [ADR 0014](../adr/0014-native-tool-calling.md), [ADR 0015](../adr/0015-mcp-over-http-two-servers.md), [ADR 0016](../adr/0016-spring-boot-mcp-server.md)

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

## Concept 4 — The same tools in Java: Spring Boot and Spring AI (2.2b)

**The problem.** A contract is only convincing if something very different can meet it. The Java server is that something: another language, another framework, another way of talking to the database, and the same four tools.

**The idea.** `services/mcp-java` is a small Spring Boot application. Each tool is a Java method marked `@McpTool`; 🟦Spring AI reads the method, builds the 🟦MCP tool list and its JSON Schema, and serves them over streamable HTTP at `/mcp`. The two servers side by side:

| Job | Python (FastMCP) | Java (Spring Boot + Spring AI) |
| --- | --- | --- |
| Declare a tool | `@server.tool()` on an `async def` | `@McpTool(name=..., description=...)` on a method of a `@Component` |
| Describe an argument | A type hint (`company_name: str`) | `@McpToolParam(description=..., required=...)`; the **parameter name** is the argument name |
| Optional argument | `str \| None = None` | `required = false` (a `Boolean`, so "missing" is `null`) |
| Database | `asyncpg` pool, raw SQL | `JdbcClient`, the same raw SQL |
| Settings | `app/config.py` and environment variables | `application.yml` and environment variables |
| Run as a service | `python -m app.mcp.server` (Uvicorn) | `java -jar` (embedded Tomcat) |
| Tests | pytest, a real HTTP round trip | JUnit 5, `@SpringBootTest` and a real MCP client |

![The 2.2b module map: inside services/mcp-java, CrmTools has four @McpTool methods and uses JdbcCrmRepository (SQL and audit rows), HttpRetrievalClient (HTTP/1.1 calls to the Python API) and CompanyRef (name matching). Java tests and the contract checker both test CrmTools. A new /search endpoint on the Python API receives the document search calls.](../img/diagrams/stage2-module-map.png)

<sub>Diagram source: [stage2-module-map.mmd](../diagrams/stage2-module-map.mmd)</sub>

### Who owns what

The Java server reads and writes the same Postgres tables, but **the schema still belongs to the Python API's migrations**: the Java side is only a client of it (who should own the CRM schema is a Stage 6 question). Document search stays in Python too, because 🟪embeddings and the 🟪vector store are Python's; the Java `search_documents` 🟪tool calls a new `POST /api/v1/documents/search` on the API, which returns exactly what the FastMCP tool returns. The Java server therefore does not write an audit row for that tool; the API does.

### Proof that they are interchangeable

Three checks, all against the one contract:

1. **A Java test** (`ContractTest`) starts the real server on a random port and runs the contract with a real MCP client; only the database and the API are fakes.
2. **CI** runs `contracts/check_server.py` against the running container, as it does for FastMCP.
3. **A side-by-side run**: nine calls (known and unknown companies, a partial name, a proposed task, a confirmed task) sent to both servers returned identical JSON, and both wrote the same kinds of audit rows.

```text
$ docker compose exec api-py python /tmp/contracts/check_server.py http://mcp-spring:8003/mcp
http://mcp-spring:8003/mcp: OK (4 cases)
```

### Two traps we met

> [!WARNING]
> **1. The argument name is the parameter name.** Spring AI has no way to rename a tool argument, so the Java parameters are written `company_name`, not `companyName`, exactly as the contract says. A comment on the class explains it, so nobody "fixes" it.
>
> **2. A bug only the real stack showed.** The first live `search_documents` call through Java got `422 body: Field required` from the Python API, although the unit test of the HTTP client passed. Java's HTTP client first offers an upgrade to HTTP/2, and Uvicorn (the API's server) then loses the body of a POST. The client now speaks HTTP/1.1 only, and a test fails if it ever sends the upgrade header again. The lesson is the one from 2.2a: run the real thing.

### Running it

```bash
just up-java                     # builds and starts mcp-spring on :8003 (profile "java")
just mcp-contract http://localhost:8003/mcp
just java-test                   # Maven build and the Java tests (Java 21 and Maven needed)
```

Until it runs, the web app shows the Spring Boot radio button as "not reachable" and greyed out.

### Lessons

> [!IMPORTANT]
> 1. **Interchangeable means checked by something neither side owns.** The same file runs against Python and Java.
> 2. **Keep one owner per thing.** Schema and 🟪retrieval stay in Python; Java asks for them instead of copying them.
> 3. **Compare behaviour, not only schemas.** The side-by-side run is stricter than the four contract cases.
> 4. **A service that works in a unit test can still fail on the wire.** Test across the real network boundary.

> [!NOTE]
> **What we have not seen.** No model has driven a tool call through the Java server (no 🟩OpenRouter key). The two servers' Host-header protection also differs: only the FastMCP server has the allowlist.

---

## Code tour: what changed in 2.2b, and why

Bright green is new in this sub-stage (2.2b), amber is an existing module that changed in it, grey is existing and untouched (Stages 0 to 2.2a are collapsed to one grey box). Markers in the tables: 🟢 new, 🟡 changed, ⚪ earlier. The map is in Concept 4 above.

### New files

| | Added in | File | What it is for | Names to look at | Used by |
| --- | --- | --- | --- | --- | --- |
| 🟢 | 2.2b | [`services/mcp-java/pom.xml`](../../services/mcp-java/pom.xml) | The Maven build: Spring Boot 4.0.9, 🟦Spring AI 2.0.2, Java 21 | `spring-ai-starter-mcp-server-webmvc` | Maven, CI |
| 🟢 | 2.2b | [`CrmTools.java`](../../services/mcp-java/src/main/java/com/customercompass/mcp/CrmTools.java) | The four tools | `@McpTool`, `getCompanySummary()`, `createFollowupTask()` | Spring AI |
| 🟢 | 2.2b | [`JdbcCrmRepository.java`](../../services/mcp-java/src/main/java/com/customercompass/mcp/JdbcCrmRepository.java), [`CrmRepository.java`](../../services/mcp-java/src/main/java/com/customercompass/mcp/CrmRepository.java) | The SQL (same as the Python), and the interface the tests fake | `summary()`, `createTask()`, `audit()` | `CrmTools` |
| 🟢 | 2.2b | [`CompanyRef.java`](../../services/mcp-java/src/main/java/com/customercompass/mcp/CompanyRef.java) | Company-name matching, the same rule as Python | `findMentioned()` | `CrmTools` |
| 🟢 | 2.2b | [`HttpRetrievalClient.java`](../../services/mcp-java/src/main/java/com/customercompass/mcp/HttpRetrievalClient.java) | Calls the Python API for document search; HTTP/1.1 only | `search()` | `CrmTools` |
| 🟢 | 2.2b | [`application.yml`](../../services/mcp-java/src/main/resources/application.yml), [`Dockerfile`](../../services/mcp-java/Dockerfile) | Settings (🟦MCP transport, datasource, API address); the image | `spring.ai.mcp.server.*` | Spring, Compose |
| 🟢 | 2.2b | `services/mcp-java/src/test/` (4 test classes, `FakeCrm`) | Contract run in-process, tool rules, the HTTP client, name matching | `ContractTest` | CI |
| 🟢 | 2.2b | [`tests/test_documents_search.py`](../../apps/api-py/tests/test_documents_search.py) | The new search endpoint | | CI |
| 🟢 | 2.2b | [ADR 0016](../adr/0016-spring-boot-mcp-server.md) | The decision, differences and what is not verified | | Readers |
| ⚪ | 2.2a | [`contracts/`](../../contracts/README.md), `app/mcp/registry.py`, `routes/mcp.py`, the web picker | The shared contract, backend choice, radio buttons | | Both servers |

### Existing files that changed, and what changed

| | Changed in | File | Change |
| --- | --- | --- | --- |
| 🟡 | 2.2b | `app/routes/documents.py` | `POST /documents/search` (503 with the reason when the 🟪embeddings key is missing) |
| 🟡 | 2.2b | `contracts/check_server.py`, `tests/test_mcp_contract.py` | An optional argument may be spelled "string" or "string or null" |
| 🟡 | 2.2b | `docker-compose.yml`, `.github/workflows/ci.yml`, `release.yml`, `dependabot.yml`, `justfile` | The `mcp-spring` service (profile `java`), a Java CI job, contract and reachability checks, image scan, release image, Maven updates, `just up-java` and `just java-test` |
| 🟡 | 2.2b | Web: `McpServerPicker.tsx` | A server that is not reachable is disabled too |
| 🟡 | 2.2b | `docs/` | API reference, architecture, tech stack, roadmap, this guide |
| ⚪ | 2.2a | `server.py`, `client.py`, `config.py`, `routes/chat.py` | FastMCP over HTTP and the backend choice |

### A good reading order

1. **`CrmTools.java`**: put it next to `app/mcp/server.py` and `tools.py`; the table above is the map between them.
2. **`JdbcCrmRepository.java`**: the same SQL, in Java.
3. **`ContractTest.java`**: how a Java test talks real MCP.
4. **`HttpRetrievalClient.java`**: the HTTP/1.1 comment is the story of the bug.
5. **`application.yml`**: three lines turn the starter into a streamable HTTP MCP server.

## What this stage added to the tech stack (so far)

| Tool | What it does in plain words | Where to look |
| --- | --- | --- |
| **Pydantic** (already used) | Describes the shape of data, checks it, and produces JSON Schema | `apps/api-py/app/mcp/schemas.py` |
| **🟪Tool calling** (provider feature, through 🟦LiteLLM) | The model asks for a function by name with JSON arguments | `app/llm/gateway.py` |
| **🟦FastMCP** (the `MCPServer` of the official `mcp` SDK, 2.2a) | A long-running tool server that speaks MCP over HTTP | `apps/api-py/app/mcp/server.py` |
| **Spring Boot + 🟦Spring AI 🟦MCP server** (2.2b) | The same four tools written in Java; Spring AI turns `@McpTool` methods into an MCP server | `services/mcp-java/` |
| **Maven** (2.2b) | Java's build tool: downloads dependencies, compiles, tests, packages | `services/mcp-java/pom.xml` |
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
- **JDBC / JdbcClient**: Java's standard way to talk to a SQL database; `JdbcClient` is Spring's small fluent wrapper.
- **JUnit**: Java's standard unit-testing library.
- **Long-lived service**: a program that keeps running and answers many requests, as opposed to one started for each request.
- **Maven**: Java's build tool; `pom.xml` lists what the project depends on and how to build it.
- **Pydantic**: a Python library that describes data shapes, validates them and can export JSON Schema.
- **Streamable HTTP**: the 🟦MCP transport that carries requests and answers over ordinary HTTP, so a tool server can be a separate service.
- **Spring Boot**: a Java framework that starts an application with sensible defaults (web server, configuration, database access).
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

<details><summary>12. In 🟦Spring AI, where does a tool's argument name come from, and what does that force on the Java code?</summary>

From the Java parameter name, because `@McpToolParam` has no name attribute. The contract says `company_name`, so the Java parameters are snake_case on purpose.
</details>

<details><summary>13. Why does the Java <code>search_documents</code> tool call the Python API instead of searching itself?</summary>

🟪Embeddings and the 🟪vector store belong to the Python API. A second implementation of 🟪retrieval would have to be kept equal to the first. Calling the API keeps one owner; the API also writes the audit row for that tool.
</details>

<details><summary>14. The HTTP client's unit test passed, yet the first live search got <code>422 body: Field required</code>. What was wrong, and what keeps it from coming back?</summary>

Java's HTTP client offers an upgrade to HTTP/2 by default, and Uvicorn then loses the body of a POST. The client now speaks HTTP/1.1 only, and a test fails if the upgrade header is sent. The unit test missed it because the stand-in server did not behave like Uvicorn.
</details>

<details><summary>15. Name three ways the two servers are shown to be interchangeable.</summary>

The Java in-process contract test, the CI check of the running container with `check_server.py`, and a side-by-side run of nine identical calls that returned identical JSON.
</details>

<details><summary>16. Who owns the database schema, and who owns document search, now that a Java server exists?</summary>

The Python API in both cases: the schema through its Alembic migrations (the Java server is only a client of it, and the question comes back in Stage 6), and search through its retrieval code, which Java reaches over HTTP.
</details>

## Further reading

- OpenAI 🟪function calling guide (the format 🟦LiteLLM follows): <https://platform.openai.com/docs/guides/function-calling>
- LiteLLM, function calling: <https://docs.litellm.ai/docs/completion/function_call>
- Pydantic, JSON Schema: <https://docs.pydantic.dev/latest/concepts/json_schema/>
- 🟦Spring AI, 🟦MCP server (streamable HTTP): <https://docs.spring.io/spring-ai/reference/api/mcp/mcp-streamable-http-server-boot-starter-docs.html>
- Spring AI, MCP annotations (`@McpTool`): <https://docs.spring.io/spring-ai/reference/api/mcp/mcp-annotations-server.html>
- Model Context Protocol: <https://modelcontextprotocol.io/>
