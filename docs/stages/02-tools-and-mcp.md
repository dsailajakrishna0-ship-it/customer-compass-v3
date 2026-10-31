# Stage 2 — Tools and MCP: letting the model do things safely

> **Level:** beginner friendly; read [Stage 1](01-model-layer.md) first (the gateway). **Reading time:** about 20 minutes for what is written so far.
> **Status:** in progress. **2.1 is written; 2.2 (🟦MCP over HTTP) is added when it is built.**
> **Roadmap:** [Stage 2](../roadmap.md#stage-2--tools-and-mcp) · **Decisions:** [ADR 0014](../adr/0014-native-tool-calling.md) (more to come)

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

## Code tour: what changed in 2.1, and why

Bright green is new in this sub-stage, amber is an existing module that changed, grey is existing and untouched (Stage 0 and 1 are collapsed to one grey box). Markers in the tables: 🟢 new, 🟡 changed, ⚪ earlier.

![Module map after sub-stage 2.1: the chat route's tool loop was rewritten and now calls the gateway, which gained tools and tool_choice and parses tool calls into a ToolCall type, and a new schemas module with one Pydantic model per tool. The MCP client, server and tools are untouched. Two new test files cover the loop and the match between schemas and the server. Stages 0 and 1 are collapsed into one grey box.](../img/diagrams/stage2-module-map.png)

<sub>Diagram source: [stage2-module-map.mmd](../diagrams/stage2-module-map.mmd)</sub>

### New files

| | Added in | File | What it is for | Names to look at | Used by |
| --- | --- | --- | --- | --- | --- |
| 🟢 | 2.1 | [`app/mcp/schemas.py`](../../apps/api-py/app/mcp/schemas.py) | What the model may pass to each tool; builds the tool definitions and validates calls | `TOOL_ARGS`, `tool_definitions()`, `validate_arguments()` | `routes/chat.py` |
| 🟢 | 2.1 | [`tests/test_chat_tools.py`](../../apps/api-py/tests/test_chat_tools.py) | The loop's rules with a scripted model and a fake tool server | `World`, `reply()`, `call()` | CI |
| 🟢 | 2.1 | [`tests/test_tool_schemas.py`](../../apps/api-py/tests/test_tool_schemas.py) | Schemas match the server; `confirm` is never offered; bad arguments refused | | CI |
| 🟢 | 2.1 | [ADR 0014](../adr/0014-native-tool-calling.md) | The decision and what is not verified | | Readers |
| ⚪ | 1.2 | [`app/llm/gateway.py`](../../apps/api-py/app/llm/gateway.py) | The one door for every model call | `generate()` | Routes, guard |

### Existing files that changed, and what changed

| | Changed in | File | Change |
| --- | --- | --- | --- |
| 🟡 | 2.1 | `app/routes/chat.py` | `/chat/tools` rewritten: native 🟪tool calls, validation, error results, bounded loop; the fenced-text 🟪prompt and regular expression are gone |
| 🟡 | 2.1 | `app/llm/gateway.py` | `generate(..., tools=, tool_choice=)`; reads tool calls; an answer may be tool calls with no text |
| 🟡 | 2.1 | `app/llm/types.py` | `ToolCall`; `GenerationResult.tool_calls` |
| 🟡 | 2.1 | `tests/test_gateway.py`, `tests/test_mcp_tools.py` | Tool-call cases added; the old regular-expression tests removed |
| 🟡 | 2.1 | `docs/` (api reference, architecture, tech stack, frontend flow) | The fenced protocol is described as replaced |
| ⚪ | 1.x | settings, logs, gateway, cloud-only models, test fakes | See [Stage 1](01-model-layer.md) |

### A good reading order

1. **`app/mcp/schemas.py`**: under 80 lines; the whole contract between model and tools.
2. **`routes/chat.py`, `_run_tool_call()`**: every way a call can go wrong, and what the model is told.
3. **`routes/chat.py`, `tools_chat()`**: the bounded loop.
4. **`tests/test_chat_tools.py`**: read the test names; they are the rules.
5. **`gateway.py`, `_parse_tool_calls()`**: bad JSON becomes a value, not a crash.

## What this stage added to the tech stack (so far)

| Tool | What it does in plain words | Where to look |
| --- | --- | --- |
| **Pydantic** (already used) | Describes the shape of data, checks it, and produces JSON Schema | `apps/api-py/app/mcp/schemas.py` |
| **🟪Tool calling** (provider feature, through 🟦LiteLLM) | The model asks for a function by name with JSON arguments | `app/llm/gateway.py` |

## V2 vs V3 in this area

| | V2 | V3 (2.1) | Why it changed |
| --- | --- | --- | --- |
| How a call is signalled | A fenced text block in the reply, found with a regular expression | The provider's structured tool-call field | The small local model that needed the workaround is gone |
| Arguments | Whatever JSON the model wrote | Validated against a Pydantic model | Model output is untrusted input |
| `confirm` | Overwritten after the model sent it | Not in the schema; rejected if sent | A control the model must not use should not be offered |
| Bad calls | Cost a turn | An error result the model can correct | Models recover from clear errors |

## Glossary

- **Function definition**: the description of a tool given to the model: name, purpose and a JSON Schema for the arguments.
- **JSON Schema**: a standard way to describe the shape of JSON data (which fields, which types, which are required).
- **Pydantic**: a Python library that describes data shapes, validates them and can export JSON Schema.
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

## Further reading

- OpenAI 🟪function calling guide (the format 🟦LiteLLM follows): <https://platform.openai.com/docs/guides/function-calling>
- LiteLLM, function calling: <https://docs.litellm.ai/docs/completion/function_call>
- Pydantic, JSON Schema: <https://docs.pydantic.dev/latest/concepts/json_schema/>
- 🟦Model Context Protocol: <https://modelcontextprotocol.io/>
