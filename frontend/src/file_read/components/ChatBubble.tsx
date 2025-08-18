// frontend/src/file_read/components/ChatBubble.tsx
import { useState } from "react";
import { Copy, Check } from "lucide-react";
import MarkdownMessage from "./MarkdownMessage";

export default function ChatBubble({
  role,
  text,
}: {
  role: "user" | "assistant";
  text: string;
}) {
  const isUser = role === "user";
  const content = text?.trim() ?? "";
  if (role === "assistant" && !content) return null;

  const [copiedMsg, setCopiedMsg] = useState(false);

  const copyWholeMessage = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedMsg(true);
      setTimeout(() => setCopiedMsg(false), 4000); // 4s, then revert
    } catch {}
  };

  return (
    <div className="mb-2">
      {/* Bubble */}
      <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
        <div
          className={`max-w-[80%] w-fit break-words rounded-2xl px-4 py-2 shadow-sm
                      prose prose-base max-w-none
            ${isUser ? "bg-black text-white prose-invert" : "bg-white border text-gray-900"}`}
          style={{ wordBreak: "break-word" }}
        >
          {/* Ensure inner markdown never exceeds bubble width */}
          <div className="max-w-full">
            <MarkdownMessage text={content} />
          </div>
        </div>
      </div>

      {/* Under-bubble toolbar (icon-only) */}
      <div className={`mt-1 flex ${isUser ? "justify-end" : "justify-start"}`}>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={copyWholeMessage}
            title={copiedMsg ? "Copied" : "Copy"}
            aria-label={copiedMsg ? "Copied" : "Copy message"}
            className="inline-flex items-center justify-center w-7 h-7 rounded border
                       bg-white text-gray-700 shadow-sm hover:bg-gray-50 transition"
          >
            {copiedMsg ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
          </button>
        </div>
      </div>
    </div>
  );
}
