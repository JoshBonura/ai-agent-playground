import { useEffect, useRef, useState } from "react";
import ComposerActions from "./Composer/ComposerActions";
import AttachmentChip from "./Composer/AttachmentChip";
import { useAttachmentUploads } from "../hooks/useAttachmentUploads";
import type { Attachment } from "../types/chat";
import type { UIAttachment } from "../hooks/useAttachmentUploads";

const FORCE_SCROLL_EVT = "chat:force-scroll-bottom";

type Props = {
  input: string;
  setInput: (v: string) => void;
  loading: boolean;
  queued?: boolean;
  onSend: (text: string, attachments?: Attachment[]) => void | Promise<void>;
  onStop: () => void | Promise<void>;
  onHeightChange?: (h: number) => void;
  onRefreshChats?: () => void;
  sessionId?: string;
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

  const {
    atts,
    addFiles,
    removeAtt,
    anyUploading,
    anyReady,
    attachmentsForPost,
    reset,
  } = useAttachmentUploads(sessionId, onRefreshChats);

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
  }, []);

  useEffect(() => {
    autogrow();
  }, [draft, atts.length]);

  const hasText = draft.trim().length > 0;

  const forceScroll = (behavior: ScrollBehavior = "auto") => {
    window.dispatchEvent(
      new CustomEvent(FORCE_SCROLL_EVT, { detail: { behavior } }),
    );
  };

  const handleSendClick = async () => {
    const v = draft.trim();
    if (loading || queued || (!v && !anyReady) || anyUploading) return;

    // 🔹 Capture attachments BEFORE we clear/reset
    const toPost = attachmentsForPost();

    // keep your scroll event semantics
    forceScroll("auto");

    // Optimistic clear of the textbox + chip UI
    setDraft("");
    setInput("");
    reset();

    try {
      await onSend(v, toPost);
    } finally {
      onRefreshChats?.();
      requestAnimationFrame(() => forceScroll("smooth"));
    }
  };

  const handleStopClick = () => {
    if (!loading && !queued) return;
    void Promise.resolve(onStop()).finally(() => onRefreshChats?.());
  };

  const pickFile = () => fileRef.current?.click();

  const onFilePicked: React.ChangeEventHandler<HTMLInputElement> = async (e) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    if (!sessionId) {
      e.target.value = "";
      return;
    }
    await addFiles(files);
    e.target.value = "";
  };

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSendClick();
    }
  }

  const disableActions = loading || queued || anyUploading;
  const showSend = hasText || anyReady;

  return (
    <div
      ref={wrapRef}
      className="relative z-10 bg-white/95 backdrop-blur border-t p-3"
    >
      {atts.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {atts.map((a: UIAttachment) => (
            <AttachmentChip key={a.uiId} a={a} onRemove={removeAtt} />
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
          disabled={queued}
        />

        <ComposerActions
          disabledUpload={disableActions || !sessionId}
          onPickFile={pickFile}
          showStop={loading || queued}
          onStop={handleStopClick}
          showSend={showSend}
          onSend={handleSendClick}
        />
      </div>
    </div>
  );
}
