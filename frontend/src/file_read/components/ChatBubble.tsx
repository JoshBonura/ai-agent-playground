import { useState } from "react";
import { Copy, Check, Trash2 } from "lucide-react";
import MarkdownMessage from "./Markdown/MarkdownMessage";

const STOP_SENTINEL_RE = /(?:\r?\n)?(?:\u23F9|\\u23F9)\s+stopped(?:\r?\n)?$/u;

export default function ChatBubble({
  role,
  text,
  showActions = true, // NEW: parent decides when to show the toolbar
  onDelete,
}: {
  role: "user" | "assistant";
  text: string;
  showActions?: boolean;
  onDelete?: () => void;
}) {
  const isUser = role === "user";
  const content = text?.trim() ?? "";
  if (role === "assistant" && !content) return null;

  // Never show the decorative stop line in assistant bubbles
  const display = isUser ? content : content.replace(STOP_SENTINEL_RE, "");

  const [copiedMsg, setCopiedMsg] = useState(false);

  const copyWholeMessage = async () => {
    try {
      await navigator.clipboard.writeText(display);
      setCopiedMsg(true);
      setTimeout(() => setCopiedMsg(false), 2000);
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
          <div className="max-w-full">
            <MarkdownMessage text={display} />
          </div>
        </div>
      </div>

      {/* Under-bubble toolbar (icon-only) */}
      {showActions && (
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

            {/* Delete for BOTH roles when provided */}
            {onDelete && (
              <button
                type="button"
                onClick={onDelete}
                title="Delete message"
                aria-label="Delete message"
                className="inline-flex items-center justify-center w-7 h-7 rounded border
                           bg-white text-gray-700 shadow-sm hover:bg-gray-50 transition"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
