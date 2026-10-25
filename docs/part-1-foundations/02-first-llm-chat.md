# Stage 2 — First local LLM chat

**Part:** I — Foundations
**Status:** Complete

> **v2 stack note:** this record was written against the original Express API
> (`apps/api`, port 3001, `/api/...`). In the current repo the API is FastAPI
> (`apps/api-py`, port 8001, `/api/v1/...`; container `customer-compass-v2-ollama`, i.e. Ollama, which runs the local
> *generating* model `qwen2.5:3b` that writes the chat answers).
> See [../testing-guide.md](../testing-guide.md) for current run/test steps.
> Paths, ports and curl examples below are kept as originally recorded.

## Goal

Introduce an LLM and a simple conversational UI without granting it CRM data
access. This isolates the mechanics and limitations of a model call from RAG.

## Delivered design

```text
React chat UI -> POST /api/chat -> Ollama HTTP API -> Qwen2.5 3B
                                      ^
                              Docker, host port 11435
```

The Express API, not the browser, calls Ollama. This keeps model configuration
and the system prompt server-side, the same boundary used for future cloud-model
providers (see Stage 4).

## Request flow

1. The UI stores the conversation in component state.
2. It sends the latest 12 user/assistant messages to `POST /api/chat`.
3. The API prepends the application system prompt.
4. Ollama generates one non-streaming response with low temperature (`0.3`) and
   a 350-token output cap.
5. The API returns `{ "message": "..." }`; the UI appends it to the transcript.

The system prompt explicitly states that the model has no CRM data. The model
therefore must not claim to know Acme, deal history, or customer discussions.

## API contract

`POST /api/chat`

```json
{"messages":[{"role":"user","content":"Explain embeddings simply."}]}
```

Each message must have role `user` or `assistant`, non-empty text under 4,000
characters, and the request can contain at most 12 messages. Invalid input is
rejected before any model request is made.

## How to run the app

The model is downloaded once into the Docker volume:

```bash
cd /home/devarapallim/Murali/git-personal/customer-compass
docker compose up -d db ollama
docker exec customer-compass-ollama ollama pull qwen2.5:3b
npm run dev
```

Open `http://localhost:5173`.

## How to test manually

1. **Confirm the model is present**
   ```bash
   docker exec customer-compass-ollama ollama list
   # expect qwen2.5:3b in the list
   ```
2. **General question via curl**
   ```bash
   curl -s -X POST http://localhost:3001/api/chat \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"Explain embeddings simply."}]}' \
     | python3 -m json.tool
   ```
   Expect a `message` field with a plain-language explanation, and no mention
   of Acme, customers, or CRM data.
3. **Ask about CRM data it should not know**
   ```bash
   curl -s -X POST http://localhost:3001/api/chat \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"What deals does Acme Fabrication have open?"}]}'
   ```
   Expect the model to say it has no access to CRM data, not to guess an answer.
4. **Invalid request rejected**
   ```bash
   curl -i -s -X POST http://localhost:3001/api/chat \
     -H "Content-Type: application/json" -d '{"messages":[]}'
   # expect HTTP 400, no model call made
   ```
5. **Browser walkthrough** — open `http://localhost:5173`:
   - The "Ask Compass" chat panel is visible below the CRM view.
   - Send a general question and confirm a response appears in the transcript.
   - Refresh the page and confirm the transcript clears (memory is not durable).

## Developer notes

- First inference can be slower because model weights load into RAM.
- Conversation memory is not durable; refreshing the page clears it.
- Context is bounded because every prior message consumes model input tokens.
- Ollama is isolated on host port 11435 to avoid a conflict with a system-wide
  Ollama service on the conventional 11434 port.
- Cloud API providers are introduced as a configurable alternative in Stage 4.

## Developer note

Files changed in this increment:

- `docker-compose.yml` — adds the `ollama` service and `ollama-data` volume.
- `apps/api/src/app.ts` — adds model configuration, system prompt, input
  validation, and `POST /api/chat`.
- `apps/api/src/app.test.ts` — adds the invalid-chat-request test.
- `apps/web/src/main.tsx` — adds local chat state, request handling, and chat UI.
- `apps/web/src/styles.css` — adds transcript, message-bubble, and input styles.
- `README.md` — documents model setup and sample questions.

No database tables were added. Conversation history currently lives only in the
browser and model weights live in the Docker volume.
