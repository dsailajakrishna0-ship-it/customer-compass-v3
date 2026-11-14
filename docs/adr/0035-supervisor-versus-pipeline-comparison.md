# ADR 0035: the supervisor against the fixed pipeline, a replayable comparison (E3.3)

Status: accepted, 2026-11-14. Measures ADR 0033 and 0034 against the fixed pipeline; changes no behaviour. The Java edition's twin is its ADR 0022. **The recording is pending**: this ADR ships the harness and the method; the numbers are added when the owner approves the recording.

## Context

`POST /agent/recommend` runs a fixed pipeline (classify, evidence, documents, analyse, review, draft). `POST /agent/supervise` runs the same specialists under a supervisor that chooses the next one turn by turn, with its choices enforced in code (E3.1), plus an answer team for plain questions (E3.2). The question for the owner: when is the extra moving part worth it? This slice makes it measurable, the same way the multi-source strategies were (ADR 0032): record once, replay forever.

## Decision

- **The same ten cases as the Java edition** (`evals/supervisor/cases.json`, byte for byte): seven accounts to analyse, one plain question, two with no customer. Each case is run twice per arm (`REPEATS = 2`), 20 runs per arm, 40 requests. The cases carry what each arm is expected to do: the pipeline sends the plain question away (`route: direct`), the supervisor answers it (`status: answered`).
- **What is recorded per run:** status and company, whether the task table changed (it must not: nothing is written before a confirm), model calls (`llmCalls`), evidence items and how many came from the farm-supply handbook, whether every citation is a label that exists, the reviewer's verdict, and for the supervisor the turns, how many were model decisions, how many were overridden by code, how many used the researcher and how many wrote their own search words. Latency is recorded but is not compared by the check.
- **`just eval-supervisor` replays the table** with no keys and no network; **`just eval-supervisor-check`** fails if a count differs from `baseline.json`; **`just eval-supervisor-record`** asks the running API for what is not recorded yet (it resumes, and retries a failed or rate-limited call).
- **Counts replay exactly; latency does not**, so the baseline holds counts only.
- **The harness is proved without a recording:** `apps/api-py/tests/test_supervisor_eval.py` works the table by hand on a made-up recording, replays and checks a baseline, and runs the recording step against a stand-in API on localhost (resume, retry, a run that writes a task). It runs with the normal API tests.
- **No CI replay step yet:** a check needs a baseline, and a baseline needs the recording. The step is added in the PR that adds the recording.

## Results

Recording pending. Nothing is claimed here about which arm completes more analyses, uses more model calls or costs more time. The Java edition's measurement (ten cases, two runs per arm, `meta-llama/llama-3.1-8b-instruct`) found both arms completing the same 14 analyses, with the supervisor using more model calls and time; whether the Python edition shows the same is exactly what the recording will say.

## Limits to keep in mind when the numbers arrive

- Ten cases, two runs each, one small model: a difference of a run or two is within what a rerun could change.
- The comparison says nothing about answer quality beyond valid citations and the reviewer's verdict.
- The farm-supply items counted for the supervisor come from the researcher; the pipeline never searches the second corpus.

## Consequences

- The Python and Java editions will be measured on the same cases, so their tables can be read side by side.
- The recording costs live model and embedding calls (see the PR); the replay is free.
