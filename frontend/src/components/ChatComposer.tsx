import { useEffect, useRef, useState } from "react";

type Props = {
  input: string;
  setInput: (v: string) => void;
  loading: boolean;
  onSend: () => void;
  onStop: () => void;  // onStop will be triggered by the stop button
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

  // Local state to track the textarea text
  const [draft, setDraft] = useState(input);

  // Keep draft in sync when `input` changes externally
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

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendClick();
    }
  }

  const handleSendClick = () => {
    setDraft(""); // clear local
    setInput(""); // clear parent
    onSend();  // Trigger send action
  };

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
            setInput(e.target.value); // keep parent in sync
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
          <button
            className="px-4 py-2 rounded-lg bg-black text-white disabled:opacity-50"
            onClick={handleSendClick}
            disabled={loading || !draft.trim()}
          >
            {loading ? "Sending…" : "Send"}
          </button>
          {loading && (
            <button className="px-3 py-2 rounded-lg border" onClick={onStop}>
              Stop
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
