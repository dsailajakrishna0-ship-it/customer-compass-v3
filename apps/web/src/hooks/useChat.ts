import { useState, type FormEvent } from "react";
import { recommendForAccount, sendChat } from "../api/chat";
import { useChatSession } from "../context/ChatSessionContext";
import type { ChatMessage } from "../types";

/** Chat input + send logic, wired to the active ChatSessionContext (mode/model/history). */
export function useChat(): {
  question: string;
  setQuestion: (value: string) => void;
  isAsking: boolean;
  askQuestion: (event: FormEvent<HTMLFormElement>) => void;
} {
  const { chatMode, cloudModel, messages, setMessages } = useChatSession();
  const [question, setQuestion] = useState("");
  const [isAsking, setIsAsking] = useState(false);

  function askQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (!text || isAsking) return;
    const history = [...messages, { role: "user" as const, content: text }];
    setMessages(history);
    setQuestion("");
    setIsAsking(true);

    const requestBody: { messages: ChatMessage[]; model?: string } = { messages: history.slice(-12) };
    // Without a chosen model the server uses its default (models.yaml)
    if (cloudModel) requestBody.model = cloudModel;

    // Stage 10: agent mode runs the bounded workflow instead of a single chat call
    if (chatMode === "agent") {
      recommendForAccount({ message: text, model: requestBody.model })
        .then((run) => {
          setMessages((current) => [
            ...current,
            { role: "assistant", content: run.route === "direct" ? (run.message ?? "") : "", agentRun: run },
          ]);
        })
        .catch(() => {
          setMessages((current) => [
            ...current,
            { role: "assistant", content: "I could not reach the API. Check that the local services are running." },
          ]);
        })
        .finally(() => setIsAsking(false));
      return;
    }

    sendChat(chatMode, requestBody)
      .then((body) => {
        setMessages((current) => [
          ...current,
          {
            role: "assistant",
            content: body.message ?? body.error ?? "Something went wrong.",
            citations: body.citations,
            facts: body.facts,
            scopedCompany: body.scopedCompany,
            usage: body.usage,
            guardrail: body.guardrail,
            toolsUsed: body.toolsUsed,
          },
        ]);
      })
      .catch(() => {
        setMessages((current) => [
          ...current,
          { role: "assistant", content: "I could not reach the API. Check that the local services are running." },
        ]);
      })
      .finally(() => setIsAsking(false));
  }

  return { question, setQuestion, isAsking, askQuestion };
}
