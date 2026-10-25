import { useState } from "react";
import { confirmAgentTask } from "../../api/chat";
import type { AgentRun } from "../../types";
import "./agent.css";

type ConfirmState = "idle" | "saving" | "created" | "declined" | "error";

/** Stage 10: shows one agent run: recommendation, reviewer verdict, evidence,
 * the inspectable trace, and the Confirm/Decline gate. A task is created only
 * when the user presses Confirm. */
export function AgentRunPanel({ run }: { run: AgentRun }) {
  const [confirmState, setConfirmState] = useState<ConfirmState>("idle");
  const [detail, setDetail] = useState("");

  if (run.route === "direct") return <p>{run.message}</p>;
  if (run.status !== "completed") {
    return (
      <>
        <p>{run.message ?? `The agent stopped: ${run.status}.`}</p>
        {run.trace && <TraceList run={run} />}
      </>
    );
  }

  async function decide(confirm: boolean) {
    if (!run.proposedTask) return;
    setConfirmState("saving");
    try {
      const body = await confirmAgentTask({ ...run.proposedTask, confirm });
      if (!confirm) setConfirmState("declined");
      else if (body.status === "confirmed") setConfirmState("created");
      else {
        setDetail(body.detail ?? body.message ?? "Could not create the task.");
        setConfirmState("error");
      }
    } catch {
      setDetail("Could not reach the API.");
      setConfirmState("error");
    }
  }

  const { recommendation, review, proposedTask, evidence = [] } = run;
  return (
    <div className="agent-run">
      <p className="eyebrow">Recommendation for {run.company?.name}</p>
      <p>
        <strong>{recommendation?.action}</strong>
      </p>
      <p>{recommendation?.rationale}</p>
      {review && (
        <p className={review.approved ? "agent-review ok" : "usage-fallback-tag"}>
          {review.approved
            ? `✓ Reviewer agent approved${review.revisions ? ` after ${review.revisions} revision` : ""}.`
            : `⚠ Reviewer agent did not approve: ${review.reasons.join("; ")}. Check the evidence before confirming.`}
        </p>
      )}
      {run.guardrail?.flagged && (
        <p className="usage-fallback-tag" title={run.guardrail.reasons.join(", ")}>
          ⚠ Potential prompt injection detected and neutralized.
        </p>
      )}
      <details>
        <summary>Evidence ({evidence.length})</summary>
        <ul className="citations">
          {evidence.map((item) => (
            <li key={item.label}>
              <strong>{item.label}</strong> [{item.source}] {item.text}
            </li>
          ))}
        </ul>
      </details>
      <TraceList run={run} />
      {proposedTask && (
        <div className="agent-gate">
          <p>
            Proposed follow-up task for <strong>{proposedTask.companyName}</strong>: “{proposedTask.note}”
          </p>
          {confirmState === "created" && <p className="agent-review ok">✓ Task created.</p>}
          {confirmState === "declined" && <p className="usage-tag">Declined. No task was created.</p>}
          {confirmState === "error" && <p className="usage-fallback-tag">{detail}</p>}
          {(confirmState === "idle" || confirmState === "saving" || confirmState === "error") && (
            <div className="rag-controls">
              <button type="button" disabled={confirmState === "saving"} onClick={() => decide(true)}>
                Confirm and create task
              </button>
              <button type="button" className="agent-decline" disabled={confirmState === "saving"} onClick={() => decide(false)}>
                Decline
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TraceList({ run }: { run: AgentRun }) {
  const steps = run.trace ?? [];
  return (
    <details>
      <summary>Execution trace ({steps.length} steps)</summary>
      <ol className="citations">
        {steps.map((step) => (
          <li key={step.index}>
            <strong>{step.name}</strong> ({step.kind}, {step.duration_ms} ms): {step.output_summary}
          </li>
        ))}
      </ol>
    </details>
  );
}
