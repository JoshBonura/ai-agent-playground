import { useState, useEffect, useRef } from "react";
import ChatView from "./ChatView";
import ChatComposer from "./ChatComposer";
import { useChatStream } from "../hooks/useChatStream";

export default function ChatContainer() {
  const { messages, input, setInput, loading, send, stop } = useChatStream();
  const [composerH, setComposerH] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    await send();
    // No need to clear here since ChatComposer does it instantly
  };

  // Scroll to the bottom whenever new messages are added
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages]); // This will run whenever the messages state changes

  return (
    <div className="flex flex-col h-full border rounded-lg overflow-hidden bg-white">
      {/* Scrollable chat area */}
      <div ref={containerRef} className="flex-1 overflow-y-auto">
        <ChatView messages={messages} loading={loading} bottomPad={composerH} />
      </div>

      {/* Composer pinned to bottom */}
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
