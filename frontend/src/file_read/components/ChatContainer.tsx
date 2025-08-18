import { useState, useRef } from "react";
import ChatView from "./ChatView";
import ChatComposer from "./ChatComposer";
import type { ChatMsg } from "../types/chat";

export default function ChatContainer({
  messages, input, setInput, loading, send, stop
}: {
  messages: ChatMsg[];
  input: string;
  setInput: (s: string) => void;
  loading: boolean;
  send: (text?: string) => Promise<void>;
  stop: () => Promise<void> | void;
  onRefreshChats?: () => void;
}) {
  const [composerH, setComposerH] = useState(0);

  // The only scrollable thing is this container
  const containerRef = useRef<HTMLDivElement>(null);

  const handleSend = async (text?: string) => {
    if (loading) return;
    await send(text);
  };

  return (
    <div className="flex flex-col h-full border rounded-lg overflow-hidden bg-white">
      <div ref={containerRef} className="flex-1 overflow-y-auto min-w-0">
        <ChatView
          messages={messages}
          loading={loading}
          bottomPad={composerH}
        />
      </div>

      <ChatComposer
        input={input}
        setInput={setInput}
        loading={loading}
        onSend={handleSend}
        onStop={stop}
        onHeightChange={setComposerH}
      />
    </div>
  );
}
