// frontend/src/file_read/components/ChatView/ChatView.tsx
import { useEffect, useMemo, useRef } from "react";
import type { ChatMsg } from "../../types/chat";
import type { GenMetrics, RunJson } from "../../hooks/useChatStream";
import ChatItem from "../ChatItem";
import TypingIndicator from "../../shared/ui/TypingIndicator";

// Autofollow sensitivity as a fraction of the visible height.
const SCROLL_THRESHOLD_VH = 0.75;
const MIN_THRESHOLD_PX = 24;

// Custom event name dispatched by ChatComposer on Send
const FORCE_SCROLL_EVT = "chat:force-scroll-bottom";

export default function ChatView({
  messages,
  loading,
  queued = false,
  bottomPad,
  runMetrics,
  runJson,
  onDeleteMessages,
  autoFollow = true,
}: {
  messages: ChatMsg[];
  loading: boolean;
  queued?: boolean;
  bottomPad: number;
  runMetrics?: GenMetrics | null;
  runJson?: RunJson | null;
  onDeleteMessages?: (ids: string[]) => void;
  autoFollow?: boolean;
}) {
  // Inner wrapper (not the scroller) + bottom sentinel for scrollIntoView
  const listRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Track previous stream state & assistant text length for streaming nudge
  const prevLoadingRef = useRef<boolean>(loading);
  const prevAsstLenRef = useRef<number>(0);
  const didInitialAutoscrollRef = useRef(false);

  // The *real* scroll container (ChatContainer sets data-chat-scroll)
  function getScrollEl(): HTMLElement | null {
    const el = listRef.current;
    if (!el) return null;
    return el.closest<HTMLElement>("[data-chat-scroll]") ?? el;
  }

  // Are we close enough to the bottom of the scroll container?
  function isNearBottom(ratio = SCROLL_THRESHOLD_VH): boolean {
    const el = getScrollEl();
    if (!el) return true; // default to follow if unsure
    const threshold = Math.max(MIN_THRESHOLD_PX, el.clientHeight * ratio);
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    return dist <= threshold;
  }

  // Programmatic scroll helper
  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    bottomRef.current?.scrollIntoView({ behavior, block: "end" });
  };

  // 🔹 NEW: On first open (first time messages appear), auto-scroll to bottom
  useEffect(() => {
    if (didInitialAutoscrollRef.current) return;
    if (messages.length === 0) return;
    didInitialAutoscrollRef.current = true;

    // Do it twice (now and next frame) to account for layout/measure changes
    scrollToBottom("auto");
    requestAnimationFrame(() => scrollToBottom("auto"));
  }, [messages.length]);

  // 🔹 Respond to a global "force scroll" event from ChatComposer (Send)
  useEffect(() => {
    const handler = (evt: Event) => {
      const behavior =
        (evt as CustomEvent<{ behavior?: ScrollBehavior }>).detail?.behavior ??
        "smooth";
      bottomRef.current?.scrollIntoView({ behavior, block: "end" });
    };
    window.addEventListener(FORCE_SCROLL_EVT, handler as EventListener);
    return () => window.removeEventListener(FORCE_SCROLL_EVT, handler as EventListener);
  }, []);

  // --- Assistant streaming deltas: gentle nudge only if already near bottom ---
  const lastAssistantIndex = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return i;
    }
    return -1;
  }, [messages]);

  const asstText =
    lastAssistantIndex >= 0 ? (messages[lastAssistantIndex]?.text ?? "") : "";

useEffect(() => {
  if (lastAssistantIndex < 0) return;

  const len = asstText.length;
  const prev = prevAsstLenRef.current || 0;
  prevAsstLenRef.current = len;

  if (!autoFollow) return;

  // Nudge whenever content grows, but only if already near bottom
  if (len > prev && isNearBottom()) {
    scrollToBottom("auto");
  }
}, [lastAssistantIndex, asstText, autoFollow]);

  // --- Streaming finished: settle to bottom only if near bottom ---
  useEffect(() => {
    const prev = prevLoadingRef.current;
    const cur = loading;
    prevLoadingRef.current = cur;

    if (prev && !cur && autoFollow && isNearBottom()) {
      scrollToBottom("smooth");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, autoFollow]);

  // --- Optional: when composer height changes, keep bottom visible only if near bottom ---
  useEffect(() => {
    if (autoFollow && isNearBottom()) {
      bottomRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
    }
  }, [bottomPad, autoFollow]);

  const lastMsg = messages[messages.length - 1];

  return (
    <div
      ref={listRef}
      className="p-4 space-y-3 bg-gray-50 min-w-0"
      style={{ paddingBottom: bottomPad }}
    >
      {messages.map((m, idx) => (
        <ChatItem
          key={m.id}
          m={m}
          idx={idx}
          loading={loading}
          lastAssistantIndex={lastAssistantIndex}
          runJsonLive={runJson ?? null}
          runMetricsLive={runMetrics ?? null}
          onDelete={onDeleteMessages ? (id) => onDeleteMessages([id]) : undefined}
        />
      ))}

      {(loading || queued) &&
        !(lastMsg?.role === "assistant" && (lastMsg.text?.trim().length ?? 0) > 0) && (
          <TypingIndicator />
        )}

      {/* Sentinel used for programmatic scrolls */}
      <div ref={bottomRef} className="h-0" />
    </div>
  );
}
