# 0012 — Agent limits (steps and time)

- **Status:** Accepted (the numbers are provisional until measured on hosted models)
- **Date:** 2026-10-31
- **Roadmap sub-stage:** 1.4

## Context

The agent workflow stops on hard limits so a confused or slow model cannot run forever or loop: `AGENT_MAX_STEPS=8`, `AGENT_TIMEOUT_SECONDS=180` and `AGENT_MAX_REVISIONS=1` (settings in `app/config.py`). They were chosen in V2 for a small local model on a CPU:

- A normal run is **6 budgeted steps** (identify the company, three evidence reads, analyst, reviewer) and each revision adds 2. The eight-step limit therefore allows exactly one revision.
- The V2 baseline measured a mean of about **41 s per case** (trace length 6 to 10 including the drafter and the confirmation gate, which are not budgeted), so 180 s was a generous ceiling for a slow model.

Chat now uses hosted free models ([ADR 0010](0010-cloud-only-models.md)), whose speed differs and changes over time. The roadmap asked to re-measure the limits.

## Decision

1. **Keep the current defaults for now.** The step limit is a safety rule about the *shape* of the workflow, not a speed setting, so it does not depend on the model. The timeout is a speed setting and should follow data.
2. **Measure, don't guess.** `just measure-limits` (`evals/measure_limits.py`) runs the agent golden cases several times against a running API and reports wall time (p50, p90, max), the time of a single model call, trace length, the share of the timeout used at p90 and how many runs ended as something other than `completed`. It *suggests* a timeout (the slowest completed run plus 50%, rounded up to 30 s); a person decides. The statistics and the collection logic are tested offline.
3. **Record the numbers here when they exist.** Until then this ADR holds the V2 numbers above.

## Status of the measurement

**Not done.** Measuring needs a real `OPENROUTER_API_KEY`, which was not available when this was written, so no hosted-model numbers exist yet and the roadmap exit criterion ("a limits ADR holds the new numbers") is only partly met: the method and the tool are in place, the numbers are not. When a key is available: run `just up && just seed && just measure-limits`, paste the summary into a new section below, and change the settings only if the data says so.

## Alternatives considered

- **Raise or lower the numbers now from intuition:** free-model speed varies by the hour; a guess would be no better than the V2 number and would look authoritative.
- **Remove the timeout:** a hung provider would hold the request open; the gateway has its own per-call timeouts but the workflow limit protects the whole run.
- **Make the limit adaptive (derive it from recent latency):** more machinery than the problem needs; revisit if the measurements show wide swings.

## Consequences

- The limits keep protecting the run; they may be too generous or too tight for hosted models until measured.
- Free models rotate, so a measurement is a snapshot: repeat it when the fallback chain changes.
