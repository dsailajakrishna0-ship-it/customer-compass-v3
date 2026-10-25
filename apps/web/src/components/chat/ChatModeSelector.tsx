import type { ChatMode, LlmProvider, ModelCatalog } from "../../types";
import { MODE_COPY } from "../../context/ChatSessionContext";
import { ModelPicker } from "./ModelPicker";

type ChatModeSelectorProps = {
  chatMode: ChatMode;
  onChangeMode: (mode: ChatMode) => void;
  provider: LlmProvider;
  onChangeProvider: (provider: LlmProvider) => void;
  cloudModel: string;
  onChangeCloudModel: (modelId: string) => void;
  cloudModels: ModelCatalog;
  isIngesting: boolean;
  onIngest: () => void;
};

/** Controls row: ingest button, chat-mode dropdown, LLM provider dropdown, and (when cloud is picked) the OpenRouter model dropdown. */
export function ChatModeSelector({
  chatMode,
  onChangeMode,
  provider,
  onChangeProvider,
  cloudModel,
  onChangeCloudModel,
  cloudModels,
  isIngesting,
  onIngest,
}: ChatModeSelectorProps) {
  return (
    <div className="rag-controls">
      <button type="button" onClick={onIngest} disabled={isIngesting}>
        {isIngesting ? "Ingesting…" : "Ingest documents"}
      </button>
      <div className="provider-select">
        <label htmlFor="chat-mode-select">Chat mode:</label>
        <select id="chat-mode-select" value={chatMode} onChange={(event) => onChangeMode(event.target.value as ChatMode)}>
          <option value="general">{MODE_COPY.general.label}</option>
          <option value="rag">{MODE_COPY.rag.label}</option>
          <option value="crm">{MODE_COPY.crm.label}</option>
          <option value="tools">{MODE_COPY.tools.label}</option>
          <option value="agent">{MODE_COPY.agent.label}</option>
        </select>
      </div>
      <div className="provider-select">
        <label htmlFor="provider-select">Model:</label>
        <select id="provider-select" value={provider} onChange={(event) => onChangeProvider(event.target.value as LlmProvider)}>
          <option value="ollama">Local (Ollama · qwen2.5:3b)</option>
          <option value="cloud">Cloud (OpenRouter, free tier)</option>
        </select>
      </div>
      {provider === "cloud" && (
        <div className="provider-select">
          <label htmlFor="cloud-model-select">OpenRouter model:</label>
          <ModelPicker
            id="cloud-model-select"
            cloudModel={cloudModel}
            onChangeCloudModel={onChangeCloudModel}
            cloudModels={cloudModels}
          />
        </div>
      )}
    </div>
  );
}
