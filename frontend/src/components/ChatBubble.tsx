import { useState } from "react";
import { Copy, Check, Trash2 } from "lucide-react";
import MarkdownMessage from "./Markdown/MarkdownMessage";
import { stripRunJson } from "../shared/lib/runjson";
import type { Attachment } from "../types/chat"; // ✅ import Attachment type

const STOP_SENTINEL_RE = /(?:\r?\n)?(?:\u23F9|\\u23F9)\s+stopped(?:\r?\n)?$/u;

export default function ChatBubble({
  role,
  text,
  attachments = [], // ✅ new prop
  showActions = true,
  onDelete,
}: {
  role: "user" | "assistant";
  text: string;
  attachments?: Attachment[]; // ✅ allow attachments
  showActions?: boolean;
  onDelete?: () => void;
}) {
  const isUser = role === "user";
  const raw = text ?? "";
  const { text: stripped } = stripRunJson(raw);
  let content = stripped.trim();

  if (!isUser) content = content.replace(STOP_SENTINEL_RE, "");

  const hasOnlyAttachments =
    isUser && (!content || content.length === 0) && attachments.length > 0;

  if (role === "assistant" && !content && attachments.length === 0) return null;

  const [copiedMsg, setCopiedMsg] = useState(false);
  const copyWholeMessage = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedMsg(true);
      setTimeout(() => setCopiedMsg(false), 2000);
    } catch {}
  };

  return (
    <div className="mb-2">
      <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
        <div
          className={`max-w-[80%] w-fit break-words rounded-2xl px-4 py-2 shadow-sm
                      prose prose-base max-w-none
            ${isUser ? "bg-black text-white prose-invert" : "bg-white border text-gray-900"}`}
        >
          {/* ✅ Render attachments */}
          {attachments.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {attachments.map((att) => (
                <div
                  key={`${att.sessionId || "global"}:${att.source || att.name}`}
                  className={`border rounded px-2 py-1 text-sm flex items-center gap-2 ${
                    isUser ? "bg-white/10 border-white/30" : "bg-white"
                  }`}
                  title={att.name || att.source}
                >
                  📎 <span className="truncate max-w-[220px]">{att.name}</span>
                </div>
              ))}
            </div>
          )}

          {content ? (
            <div className="max-w-full">
              <MarkdownMessage text={content} />
            </div>
          ) : hasOnlyAttachments ? null : isUser ? null : (
            <span className="opacity-60">…</span>
          )}
        </div>
      </div>

      {showActions && (
        <div
          className={`mt-1 flex ${isUser ? "justify-end" : "justify-start"}`}
        >
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={copyWholeMessage}
              title={copiedMsg ? "Copied" : "Copy"}
              aria-label={copiedMsg ? "Copied" : "Copy message"}
              className="inline-flex items-center justify-center w-7 h-7 rounded border
                         bg-white text-gray-700 shadow-sm hover:bg-gray-50 transition"
            >
              {copiedMsg ? (
                <Check className="w-4 h-4" />
              ) : (
                <Copy className="w-4 h-4" />
              )}
            </button>
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
