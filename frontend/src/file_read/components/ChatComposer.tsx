// frontend/src/file_read/components/ChatComposer.tsx
import { useEffect, useRef, useState } from "react";
import { SendHorizonal, Square, Paperclip, X, Check } from "lucide-react";
import { uploadRagWithProgress, deleteUploadHard } from "../data/ragApi";

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
  sessionId?: string;
};

type Att = {
  id: string;               // unique per pick
  name: string;             // file.name (used as source)
  pct: number;              // 0..100
  status: "uploading" | "ready" | "error";
  abort?: AbortController;  // to cancel in-flight
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
  sessionId,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const MAX_HEIGHT_PX = 192;

  const [isClamped, setIsClamped] = useState(false);
  const [draft, setDraft] = useState(input);

  // NEW: local attachment list
  const [atts, setAtts] = useState<Att[]>([]);

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

  useEffect(() => { autogrow(); }, [draft, atts.length]); // reflow when chips appear/disappear

  const hasText = draft.trim().length > 0;
  const anyUploading = atts.some(a => a.status === "uploading");
  const anyReady = atts.some(a => a.status === "ready");

  const forceScroll = (behavior: ScrollBehavior = "auto") => {
    window.dispatchEvent(new CustomEvent(FORCE_SCROLL_EVT, { detail: { behavior } }));
  };

  const handleSendClick = () => {
    // can send if text OR has at least one finished upload
    const v = draft.trim();
    if ((loading || queued) || (!v && !anyReady) || anyUploading) return;
    forceScroll("auto");
    setDraft("");
    setInput("");
    // Optional: clear local chips after send
    setAtts([]);
    void Promise.resolve(onSend(v)).finally(() => {
      onRefreshChats?.();
      requestAnimationFrame(() => forceScroll("smooth"));
    });
  };

  const handleStopClick = () => {
    if (!loading && !queued) return;
    void Promise.resolve(onStop()).finally(() => onRefreshChats?.());
  };

  const pickFile = () => fileRef.current?.click();

  const onFilePicked: React.ChangeEventHandler<HTMLInputElement> = async (e) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    if (!sessionId) { e.target.value = ""; return; }

    const picked = Array.from(files);
    // create local chip entries
    const news: Att[] = picked.map((f, i) => ({
      id: `${Date.now()}-${i}-${f.name}`,
      name: f.name,
      pct: 0,
      status: "uploading",
      abort: new AbortController(),
    }));
    setAtts(prev => [...prev, ...news]);

    // kick uploads
    news.forEach((att, idx) => {
      const f = picked[idx];
      uploadRagWithProgress(
        f,
        sessionId,
        (pct) => setAtts(prev => prev.map(a => a.id === att.id ? { ...a, pct } : a)),
        att.abort?.signal
      ).then(() => {
        setAtts(prev => prev.map(a => a.id === att.id ? { ...a, pct: 100, status: "ready", abort: undefined } : a));
        onRefreshChats?.();
      }).catch(() => {
        setAtts(prev => prev.map(a => a.id === att.id ? { ...a, status: "error", abort: undefined } : a));
      });
    });

    e.target.value = ""; // allow re-pick
  };

  const removeAtt = async (att: Att) => {
    // cancel in-flight
    if (att.status === "uploading" && att.abort) {
      att.abort.abort();
    }
    // hard-delete if already ingested
    if (att.status === "ready" && sessionId) {
      try { await deleteUploadHard(att.name, sessionId); } catch {}
      onRefreshChats?.();
    }
    setAtts(prev => prev.filter(a => a.id !== att.id));
  };

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendClick();
    }
  }

  const disableActions = loading || queued || anyUploading;
  const showSend = hasText || anyReady; // <- allow send even with empty text if file ready

  return (
    <div ref={wrapRef} className="relative z-50 bg-white/95 backdrop-blur border-t p-3">
      {/* Attachment chips */}
      {atts.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {atts.map((a) => (
            <div key={a.id} className="min-w-[160px] max-w-[280px] border rounded-lg px-2 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="truncate text-sm" title={a.name}>{a.name}</div>
                <button
                  className="p-1 rounded hover:bg-gray-100"
                  aria-label="Remove file"
                  onClick={() => removeAtt(a)}
                >
                  <X size={14} />
                </button>
              </div>
              <div className="mt-2 h-1.5 w-full bg-gray-200 rounded">
                <div
                  className={`h-1.5 rounded ${a.status === "error" ? "bg-red-500" : "bg-black"}`}
                  style={{ width: `${a.pct}%` }}
                />
              </div>
              <div className="mt-1 text-xs text-gray-500 flex items-center gap-1">
                {a.status === "uploading" && <span>Uploading… {a.pct}%</span>}
                {a.status === "ready" && <><Check size={14} /> Ready</>}
                {a.status === "error" && <span>Error</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <input
          ref={fileRef}
          type="file"
          multiple
          className="hidden"
          onChange={onFilePicked}
        />

        <textarea
          ref={taRef}
          value={draft}
          onChange={(e) => { setDraft(e.target.value); setInput(e.target.value); autogrow(); }}
          onInput={autogrow}
          onKeyDown={onKeyDown}
          placeholder="Ask anything…"
          className={`flex-1 border rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring ${
            isClamped ? "overflow-y-auto" : "overflow-hidden"
          }`}
          rows={1}
          style={{ maxHeight: MAX_HEIGHT_PX }}
          disabled={queued} // (optional) keep typing allowed during upload
        />

        <div className="flex items-end gap-2">
          <button
            className={`p-2 rounded-lg border hover:bg-gray-50 ${disableActions || !sessionId ? "opacity-60 cursor-not-allowed" : ""}`}
            onClick={pickFile}
            title="Upload to this chat"
            aria-label="Upload to this chat"
            disabled={disableActions || !sessionId}
          >
            <Paperclip size={18} />
          </button>

          {(loading || queued) ? (
            <button
              className="p-2 rounded-lg border hover:bg-gray-50"
              onClick={handleStopClick}
              title={queued ? "Cancel queued message" : "Stop generating"}
              aria-label={queued ? "Cancel queued message" : "Stop generating"}
            >
              <Square size={18} />
            </button>
          ) : showSend ? (
            <button
              className="p-2 rounded-lg bg-black text-white hover:bg-black/90 active:translate-y-px disabled:opacity-60"
              onClick={handleSendClick}
              title="Send"
              aria-label="Send"
              disabled={disableActions}
            >
              <SendHorizonal size={18} />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
