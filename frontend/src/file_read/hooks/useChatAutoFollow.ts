import { useEffect, useMemo, useRef } from "react";
import type { ChatMsg } from "../types/chat";

const SCROLL_THRESHOLD_VH = 0.75;
const MIN_THRESHOLD_PX = 24;
const FORCE_SCROLL_EVT = "chat:force-scroll-bottom";

export function useChatAutofollow({
  messages,
  loading,
  autoFollow = true,
  bottomPad = 0,
}: {
  messages: ChatMsg[];
  loading: boolean;
  autoFollow?: boolean;
  bottomPad?: number;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const prevLoadingRef = useRef<boolean>(loading);
  const prevAsstLenRef = useRef<number>(0);
  const didInitialAutoscrollRef = useRef(false);

  function getScrollEl(): HTMLElement | null {
    const el = listRef.current;
    if (!el) return null;
    return el.closest<HTMLElement>("[data-chat-scroll]") ?? el;
  }

  function isNearBottom(ratio = SCROLL_THRESHOLD_VH): boolean {
    const el = getScrollEl();
    if (!el) return true;
    const threshold = Math.max(MIN_THRESHOLD_PX, el.clientHeight * ratio);
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    return dist <= threshold;
  }

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    bottomRef.current?.scrollIntoView({ behavior, block: "end" });
  };

  useEffect(() => {
    if (didInitialAutoscrollRef.current) return;
    if (messages.length === 0) return;
    didInitialAutoscrollRef.current = true;
    scrollToBottom("auto");
    requestAnimationFrame(() => scrollToBottom("auto"));
  }, [messages.length]);

  useEffect(() => {
    const handler = (evt: Event) => {
      const behavior =
        (evt as CustomEvent<{ behavior?: ScrollBehavior }>).detail?.behavior ?? "smooth";
      bottomRef.current?.scrollIntoView({ behavior, block: "end" });
    };
    window.addEventListener(FORCE_SCROLL_EVT, handler as EventListener);
    return () => window.removeEventListener(FORCE_SCROLL_EVT, handler as EventListener);
  }, []);

  const lastAssistantIndex = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return i;
    }
    return -1;
  }, [messages]);

  const asstText = lastAssistantIndex >= 0 ? (messages[lastAssistantIndex]?.text ?? "") : "";

  useEffect(() => {
    if (lastAssistantIndex < 0) return;
    const len = asstText.length;
    const prev = prevAsstLenRef.current || 0;
    prevAsstLenRef.current = len;
    if (!autoFollow) return;
    if (len > prev && isNearBottom()) scrollToBottom("auto");
  }, [lastAssistantIndex, asstText, autoFollow]);

  useEffect(() => {
    const prev = prevLoadingRef.current;
    const cur = loading;
    prevLoadingRef.current = cur;
    if (prev && !cur && autoFollow && isNearBottom()) scrollToBottom("smooth");
  }, [loading, autoFollow]);

  useEffect(() => {
    if (autoFollow && isNearBottom()) {
      bottomRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
    }
  }, [bottomPad, autoFollow]);

  return { listRef, bottomRef, lastAssistantIndex };
}
