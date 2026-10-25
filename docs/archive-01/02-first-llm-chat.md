# Stage 2 — First local LLM chat

**Status:** Complete

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
providers.

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

## Local workflow

The model is downloaded once into the Docker volume:

```bash
docker compose up -d db ollama
docker exec customer-compass-ollama ollama pull qwen2.5:3b
npm run dev
```

Use the chat panel at `http://localhost:5173`, or call the endpoint with curl.
See the root README for sample questions.

## Developer notes

- First inference can be slower because model weights load into RAM.
- Conversation memory is not durable; refreshing the page clears it.
- Context is bounded because every prior message consumes model input tokens.
- Ollama is isolated on host port 11435 to avoid a conflict with a system-wide
  Ollama service on the conventional 11434 port.
- Cloud API providers are a future configuration alternative, not required now.

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
