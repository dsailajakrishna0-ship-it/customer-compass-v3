import type { FormEvent } from "react";

type ChatInputProps = {
  question: string;
  onChangeQuestion: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  isAsking: boolean;
  placeholder: string;
};

/** Question text input + send button. */
export function ChatInput({ question, onChangeQuestion, onSubmit, isAsking, placeholder }: ChatInputProps) {
  return (
    <form onSubmit={onSubmit}>
      <input
        value={question}
        onChange={(event) => onChangeQuestion(event.target.value)}
        placeholder={placeholder}
        aria-label="Chat question"
      />
      <button disabled={isAsking}>{isAsking ? "Thinking…" : "Send"}</button>
    </form>
  );
}
