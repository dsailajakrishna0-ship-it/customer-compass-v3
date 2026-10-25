import type { ChatMessage } from "../../types";
import { MessageBubble } from "./MessageBubble";

/** Scrollable list of chat messages. */
export function MessageList({ messages }: { messages: ChatMessage[] }) {
  return (
    <div className="messages">
      {messages.map((message, index) => (
        <MessageBubble message={message} key={index} />
      ))}
    </div>
  );
}
