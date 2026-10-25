import { useChatSession } from "../../context/ChatSessionContext";
import { useCloudModels } from "../../hooks/useCloudModels";
import { useChat } from "../../hooks/useChat";
import { MODE_COPY } from "../../context/ChatSessionContext";
import { ChatModeSelector } from "./ChatModeSelector";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import { useEffect } from "react";
import type { ChatMode, LlmProvider } from "../../types";

type ChatPanelProps = {
  ingestStatus: string | null;
  isIngesting: boolean;
  onIngest: () => void;
};

/** Composes the chat-mode controls, message list, and input into the full "Ask Compass" panel. */
export function ChatPanel({ ingestStatus, isIngesting, onIngest }: ChatPanelProps) {
  const { chatMode, switchChatMode, provider, setProvider, cloudModel, setCloudModel, messages } = useChatSession();
  const { cloudModels } = useCloudModels();
  const { question, setQuestion, isAsking, askQuestion } = useChat();

  // Default to the first free OpenRouter model once the catalog loads, unless
  // a prior choice was already restored from localStorage.
  useEffect(() => {
    if (cloudModels.free.length > 0 && !cloudModel) setCloudModel(cloudModels.free[0].id);
  }, [cloudModels, cloudModel, setCloudModel]);

  return (
    <section className="chat-panel">
      <div>
        <p className="eyebrow">Chat · Stages 2–10</p>
        <h2>Ask Compass</h2>
        <p>Choose a chat mode: general knowledge, document-grounded answers, the CRM copilot, the tool-calling copilot, or the account follow-up agent.</p>
        <ChatModeSelector
          chatMode={chatMode}
          onChangeMode={(mode: ChatMode) => switchChatMode(mode)}
          provider={provider}
          onChangeProvider={(next: LlmProvider) => setProvider(next)}
          cloudModel={cloudModel}
          onChangeCloudModel={setCloudModel}
          cloudModels={cloudModels}
          isIngesting={isIngesting}
          onIngest={onIngest}
        />
        {ingestStatus && <p className="ingest-status">{ingestStatus}</p>}
      </div>
      <MessageList messages={messages} />
      <ChatInput
        question={question}
        onChangeQuestion={setQuestion}
        onSubmit={askQuestion}
        isAsking={isAsking}
        placeholder={MODE_COPY[chatMode].placeholder}
      />
    </section>
  );
}
