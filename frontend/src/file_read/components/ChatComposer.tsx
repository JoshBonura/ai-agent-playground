// frontend/src/file_read/components/ChatComposer.tsx
import { useEffect, useRef, useState } from "react";
import { SendHorizonal, Square } from "lucide-react";

const FORCE_SCROLL_EVT = "chat:force-scroll-bottom";

type Props = {
  input: string;
  setInput: (v: string) => void;
  loading: boolean;
  queued?: boolean;
  onSend: (text: string) => void | Promise<void>;
  onStop: () => void | Promise<void>;
  onHeightChange?: (h: number) => void;
  onRefreshChats?: () => void;
};

export default function ChatComposer({
  input,
  setInput,
  loading,
  queued = false,
  onSend,
  onStop,
  onHeightChange,
  onRefreshChats,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const MAX_HEIGHT_PX = 192;
  const [isClamped, setIsClamped] = useState(false);
  const [draft, setDraft] = useState(input);

  useEffect(() => setDraft(input), [input]);

  const autogrow = () => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const next = Math.min(ta.scrollHeight, MAX_HEIGHT_PX);
    ta.style.height = `${next}px`;
    setIsClamped(ta.scrollHeight > MAX_HEIGHT_PX);
    if (wrapRef.current && onHeightChange) {
      onHeightChange(wrapRef.current.getBoundingClientRect().height);
    }
  };

  useEffect(() => {
    autogrow();
    const onResize = () => autogrow();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    autogrow();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  const hasText = draft.trim().length > 0;

  // 🔹 NEW: tell ChatView to scroll to bottom
  const forceScroll = (behavior: ScrollBehavior = "auto") => {
    window.dispatchEvent(
      new CustomEvent(FORCE_SCROLL_EVT, { detail: { behavior } })
    );
  };

  const handleSendClick = () => {
    const v = draft.trim();
    if (!v || loading || queued) return; // prevent sending while queued/streaming

    // Snap immediately to bottom so user sees the latest area
    forceScroll("auto");

    setDraft("");
    setInput("");
    void Promise.resolve(onSend(v)).finally(() => {
      onRefreshChats?.();
      // Settle at bottom after DOM updates
      requestAnimationFrame(() => forceScroll("smooth"));
    });
  };

  const handleStopClick = () => {
    if (!loading && !queued) return;
    void Promise.resolve(onStop()).finally(() => {
      onRefreshChats?.(); // refresh once the stop lands
    });
  };

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!loading && !queued) handleSendClick();
    }
  }

  return (
    <div ref={wrapRef} className="relative z-50 bg-white/95 backdrop-blur border-t p-3">
      <div className="flex gap-2">
        <textarea
          ref={taRef}
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            setInput(e.target.value);
            autogrow();
          }}
          onInput={autogrow}
          onKeyDown={onKeyDown}
          placeholder="Ask anything…"
          className={`flex-1 border rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring ${
            isClamped ? "overflow-y-auto" : "overflow-hidden"
          }`}
          rows={1}
          style={{ maxHeight: MAX_HEIGHT_PX }}
        />

        <div className="flex items-end gap-2">
          {(loading || queued) ? (
            <button
              className="p-2 rounded-lg border hover:bg-gray-50"
              onClick={handleStopClick}
              title={queued ? "Cancel queued message" : "Stop generating"}
              aria-label={queued ? "Cancel queued message" : "Stop generating"}
            >
              <Square size={18} />
            </button>
          ) : hasText ? (
            <button
              className="p-2 rounded-lg bg-black text-white hover:bg-black/90 active:translate-y-px"
              onClick={handleSendClick}
              title="Send"
              aria-label="Send"
            >
              <SendHorizonal size={18} />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
