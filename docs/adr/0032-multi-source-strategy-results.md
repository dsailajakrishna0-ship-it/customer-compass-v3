# ADR 0032: how the three multi-source strategies compare in the Python edition (E1.3)

Status: accepted, 2026-11-14. Measures ADR 0030's three strategies; the Java edition measured the same ones (its ADR 0019).

## Method

The same 24 labelled questions as the Java edition (`evals/knowledge-bases/questions.json`: 8 CRM-only, 8 farm-supply-only, 4 that need both, 4 that belong to neither), asked once to each strategy through `POST /api/v1/chat/multi`, with `meta-llama/llama-3.1-8b-instruct` for the router, the answer and the agent, and `gemini-embedding-001` for the embeddings. The answers are recorded in `evals/knowledge-bases/recorded.json`; `just eval-multi` replays them with no keys and no network, and `just eval-multi-check` fails if a count differs from `baseline.json` (it runs in CI). Latencies are what the recording run saw; every other number is a count.

The recording was made with the floor at 0.45 (before ADR 0031 made it 0.60), so it is the like-for-like counterpart of the Java edition's table at the global 0.45.

## Result

| | route | all | agent | Java: route / all / agent |
| --- | --- | --- | --- | --- |
| answerable questions: right sources found | 19/20 | 20/20 | 17/20 | 20/20, 20/20, 19/20 |
| searched exactly the right knowledge bases | 10/24 | 4/24 | 17/24 | |
| citations from the wrong knowledge base | 31/87 | 43/91 | 26/126 | 31/91, 43/91, 22/126 |
| no-corpus questions with no sources cited | 1/4 | 0/4 | 0/4 | 0/4, 0/4, 0/4 |
| model calls per question (mean) | 1.96 | 1.00 | 2.29 | 2, 1, 2.29 |
| failed requests | 0 | 0 | 0 | |

Where the two editions differ (all three differences are in single runs of a small model):

- **route, one CRM question** (delivery visibility, mq-06): the router sent it only to farm-supply ("delivery windows and pallet rules are in the agri-supply handbook"); the Java router searched both.
- **agent, two questions that need both** (mq-18, mq-19): the agent searched only the CRM, three times; the Java agent searched both.
- **route, one off-topic question** (mq-22): the router chose no knowledge base, so nothing was cited, which is the right outcome; the Java router chose both and cited four chunks.

## What it shows

1. **`all` is the most reliable and the simplest**: 20 of 20 in both editions, one model call, no routing decision to get wrong. Its cost is that every answer is built from both corpora (43 of 91 citations from the wrong one).
2. **The decisions are the weak part, as in Java**: `route` and `agent` lose answerable questions through their own choice of corpus, not through retrieval. A similarity floor cannot repair a routing mistake (ADR 0023 in the Java edition measured that).
3. **Off-topic questions: the floor is the weak part**: at 0.45 no strategy declines reliably (`route` once, because the router itself chose nothing). Java's calibration found the floor that fixes this; this edition's CRM floor is now 0.60 (ADR 0031). The farm-supply corpus has no calibrated floor here yet.
4. **Single runs, one small model**: a 2-question difference between the editions is within what one rerun could change. Read the pattern, not the decimals.

## Limits

- One run per question, one chat model, 24 questions. Not enough to rank `route` and `agent` against each other.
- Recorded before the 0.60 floor; re-recording with it is a separate step.
