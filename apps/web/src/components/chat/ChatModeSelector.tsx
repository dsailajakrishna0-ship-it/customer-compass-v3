import type { ChatMode, McpServers, ModelCatalog } from "../../types";
import { MODE_COPY } from "../../context/ChatSessionContext";
import { ModelPicker } from "./ModelPicker";
import { McpServerPicker } from "./McpServerPicker";

type ChatModeSelectorProps = {
  chatMode: ChatMode;
  onChangeMode: (mode: ChatMode) => void;
  cloudModel: string;
  onChangeCloudModel: (modelId: string) => void;
  cloudModels: ModelCatalog;
  mcpServers: McpServers | null;
  mcpServer: string;
  onChangeMcpServer: (id: string) => void;
  isIngesting: boolean;
  onIngest: () => void;
};

/** Controls row: ingest button, chat-mode dropdown, and the OpenRouter model dropdown. */
export function ChatModeSelector({
  chatMode,
  onChangeMode,
  cloudModel,
  onChangeCloudModel,
  cloudModels,
  mcpServers,
  mcpServer,
  onChangeMcpServer,
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
        <label htmlFor="cloud-model-select">OpenRouter model:</label>
        <ModelPicker
          id="cloud-model-select"
          cloudModel={cloudModel}
          onChangeCloudModel={onChangeCloudModel}
          cloudModels={cloudModels}
        />
      </div>
      {chatMode === "tools" && mcpServers && (
        <McpServerPicker
          servers={mcpServers.servers}
          defaultId={mcpServers.default}
          value={mcpServer}
          onChange={onChangeMcpServer}
        />
      )}
    </div>
  );
}
