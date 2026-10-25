# Frontend Architecture

`apps/web` started as a single 201-line `main.tsx` file that mixed routing,
state, data-fetching, and markup together. It was refactored in four
small, stacked PRs into layers with a single responsibility each.

## Layered design

```
┌─────────────────────────────────────────────────────────────────────┐
│                              main.tsx                               │
│                     (6 lines: mounts <App />)                       │
└───────────────────────────────┬───────────────────────────────────── ┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  App.tsx  —  ChatSessionProvider › BrowserRouter › shell chrome     │
└───────────────────────────────┬───────────────────────────────────── ┘
                                 │
                 ┌───────────────┴────────────────┐
                 ▼                                ▼
        ┌─────────────────┐              ┌──────────────────┐
        │   pages/         │              │   pages/          │
        │ DashboardPage    │  route "/"   │   ChatPage        │ route "/chat"
        └────────┬─────────┘              └─────────┬────────┘
                 │                                   │
                 ▼                                   ▼
   ┌─────────────────────────┐          ┌─────────────────────────────┐
   │ components/companies/   │          │ components/chat/            │
   │  CompanyExplorer         │          │  ChatPanel                  │
   │   ├─ CompanyList         │          │   ├─ ChatModeSelector       │
   │   └─ CompanyDetail /     │          │   ├─ MessageList            │
   │      CompanyDetailEmpty  │          │   │   └─ MessageBubble      │
   │                          │          │   │       ├─ CrmFactsPanel  │
   │                          │          │   │       └─ CitationList   │
   │                          │          │   └─ ChatInput              │
   └────────────┬─────────────┘          └─────────────┬───────────────┘
                │                                       │
                ▼                                       ▼
   ┌─────────────────────────┐          ┌─────────────────────────────┐
   │ hooks/useCompanies       │          │ hooks/useChat, useCloudModels│
   │                          │          │ context/ChatSessionContext   │
   │                          │          │  (chatMode, provider,       │
   │                          │          │   cloudModel → localStorage)│
   └────────────┬─────────────┘          └─────────────┬───────────────┘
                │                                       │
                └───────────────────┬───────────────────┘
                                     ▼
                      ┌───────────────────────────────┐
                      │  api/{client,companies,chat,  │
                      │       documents}.ts            │
                      │  (fetch wrappers, one per      │
                      │   endpoint group)               │
                      └───────────────┬───────────────┘
                                      ▼
                      ┌───────────────────────────────┐
                      │   apps/api-py (FastAPI)        │
                      └───────────────────────────────┘
```

Each box only talks to the layer directly below it — pages never call
`fetch` themselves, components never read `localStorage`, and the API
layer never imports React.

## Folder map

| Folder | Responsibility |
| --- | --- |
| `src/App.tsx` | Composition root: providers, router, shell chrome (`AppHeader`, `NavBar`) |
| `src/pages/` | One file per route; assembles components, owns page-local state (e.g. ingest status) |
| `src/components/layout/` | `AppHeader`, `NavBar` — chrome shared by every page |
| `src/components/companies/` | Dashboard UI: company list, detail pane, empty state |
| `src/components/chat/` | Chat UI: mode/provider selectors, messages, facts, citations, input |
| `src/context/` | `ChatSessionContext` — chat mode/provider/model state, persisted to `localStorage` |
| `src/hooks/` | `useCompanies`, `useChat`, `useCloudModels` — data-fetching + local UI state, decoupled from markup |
| `src/api/` | Thin `fetch` wrappers, one module per backend endpoint group |
| `src/types/` | Shared TypeScript types mirroring API response shapes |

## Tech stack

- **React 19** + **TypeScript** — function components, no class components
- **Vite** — dev server and production bundler
- **React Router v7** (`react-router-dom`) — client-side routing (`/`, `/chat`)
- **React Context** — `ChatSessionContext` for cross-cutting chat state (no Redux/Zustand; the state surface is small enough that Context + hooks is sufficient)
- **`localStorage`** — persists the user's last-chosen chat mode, provider, and cloud model across reloads (chat history is intentionally not persisted)
- Plain CSS (`styles.css`) — no CSS-in-JS or utility framework
- **`pytest`** (`apps/api-py/tests/`) on the API side — the frontend layers were verified with `tsc --noEmit` + `vite build` + manual dev-server smoke tests rather than a component test framework, since none is set up yet

## Request flow — asking a question in Chat mode

1. User types a question in `ChatInput` (`components/chat/`) and submits.
2. `ChatInput` calls `askQuestion` from the `useChat()` hook — components never touch `fetch` directly.
3. `useChat()` reads the current `chatMode` / `provider` / `cloudModel` from `useChatSession()` (the context) and calls `sendChat()` in `api/chat.ts`.
4. `api/chat.ts` picks the right endpoint — `/api/v1/chat`, `/api/v1/chat/rag`, `/api/v1/chat/crm`, or `/api/v1/chat/tools` — based on `chatMode`, and posts via the shared `apiPost` helper in `api/client.ts`.
5. The FastAPI service (the Python backend) resolves the request (plain LLM call, RAG retrieval + citations, CRM facts + RAG, or MCP tool calling), and returns a `ChatResponse`.
6. `useChat()` appends the new `ChatMessage` (with `provider`, `citations`, `facts` as applicable) to context state.
7. `ChatSessionContext` persists `chatMode`/`provider`/`cloudModel` to `localStorage` on change, and the `messages` list re-renders through `MessageList` → `MessageBubble` → `CrmFactsPanel` / `CitationList`.

## Why stacked PRs

The refactor shipped as four independent, reviewable PRs, each branched
from the previous one's merged `main`:

1. `types/` + `api/` — pure extraction, zero behavior change
2. `context/` + `hooks/` — state logic moved out of `main.tsx`
3. `components/` — markup extraction into presentational components
4. `pages/` + `App.tsx` + React Router — real routes, `main.tsx` reduced to a one-liner

Each layer was verified independently (`tsc --noEmit`, `vite build`, live
dev-server smoke test of every changed file, and the untouched `apps/api-py`
test suite) before moving to the next, so a regression in any layer is
easy to bisect to a single small PR.
