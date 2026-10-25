# Stage 1 — CRM foundation

**Status:** Complete

## Goal

Establish a small, locally runnable CRM baseline before introducing AI. The
application must let a developer inspect companies and their related CRM data.

## Delivered design

```text
React/Vite browser UI -> Express REST API -> PostgreSQL 17 (Docker)
```

The UI never accesses PostgreSQL directly. The API owns query logic and returns
JSON, which will let later AI features combine structured CRM facts with
retrieved text without exposing the database to the browser.

## Data model

`companies` is the parent entity. `contacts`, `deals`, and `interactions` each
belong to a company through `company_id`. The synthetic seed data includes three
companies, including Acme Fabrication, with realistic but fictional interactions.

| Entity | Purpose |
| --- | --- |
| Companies | account name, industry, website, relationship status |
| Contacts | people at an account |
| Deals | commercial amount, status, expected close date |
| Interactions | call, email, meeting, note, or support summary |

The schema is at `db/init.sql`. It initializes only when a new PostgreSQL volume
is created.

## API contract

- `GET /health` — verifies database connectivity.
- `GET /api/companies` — lists companies with deal and interaction counts.
- `GET /api/companies/:id` — returns company detail plus contacts, deals, and
  reverse-chronological interactions.

Invalid company IDs return `400`; unknown IDs return `404`.

## Local workflow

```bash
docker compose up -d db
npm install
npm run dev
```

Open `http://localhost:5173`. Build and test with `npm run build` and `npm test`.

## Developer notes

- PostgreSQL is infrastructure, so it runs in Docker. UI/API run locally for
  fast source reload during development.
- `expected_close_date::text` prevents a date-only CRM field shifting due to a
  browser/server timezone conversion.
- No LLM, vectors, document chunks, or RAG exist in this stage.

## Developer note

Files added in this increment:

- `package.json` — workspace scripts and shared development command.
- `docker-compose.yml` — PostgreSQL service and persistent volume.
- `db/init.sql` — schema and synthetic CRM seed data.
- `apps/api/src/db.ts` — PostgreSQL pool configuration.
- `apps/api/src/app.ts` and `apps/api/src/server.ts` — REST application and
  process entry point.
- `apps/api/src/app.test.ts` — API boundary test.
- `apps/web/src/main.tsx` and `apps/web/src/styles.css` — CRM browser UI.
- `apps/api/package.json`, `apps/web/package.json`, and TypeScript configs —
  each application’s build/runtime configuration.
