import { useEffect, useRef, useState } from "react";
import { SendHorizonal, Square } from "lucide-react";

type Props = {
  input: string;
  setInput: (v: string) => void;
  loading: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  onHeightChange?: (h: number) => void;
};

export default function ChatComposer({
  input,
  setInput,
  loading,
  onSend,
  onStop,
  onHeightChange,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const MAX_HEIGHT_PX = 192;
  const [isClamped, setIsClamped] = useState(false);
  const [draft, setDraft] = useState(input);

  useEffect(() => {
    setDraft(input);
  }, [input]);

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
  }, []);

  useEffect(() => {
    autogrow();
  }, [draft]);

  const hasText = draft.trim().length > 0;

  const handleSendClick = () => {
    const v = draft.trim();
    if (!v) return;
    onSend(v);
    setDraft("");
    setInput("");
  };

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendClick();
    }
  }

  return (
    <div
      ref={wrapRef}
      className="relative z-50 bg-white/95 backdrop-blur border-t p-3"
    >
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
          {hasText && (
            <button
              className="p-2 rounded-lg bg-black text-white hover:bg-black/90 active:translate-y-px"
              onClick={handleSendClick}
              disabled={loading}
              title="Send"
            >
              <SendHorizonal size={18} />
            </button>
          )}

          {loading && (
            <button
              className="p-2 rounded-lg border hover:bg-gray-50"
              onClick={onStop}
              title="Stop generating"
            >
              <Square size={18} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
