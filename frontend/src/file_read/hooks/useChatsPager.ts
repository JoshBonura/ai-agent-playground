import { useEffect, useMemo, useRef, useState } from "react";
import { listChatsPage } from "../data/chatApi";
import type { ChatRow } from "../types/chat";

export function useChatsPager(pageSize = 10, refreshKey?: number) {
  const [chats, setChats] = useState<ChatRow[]>([]);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [ceiling, setCeiling] = useState<string | null>(null);
  const [initialLoading, setInitialLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const loadingMoreRef = useRef(false);

  const seenIds = useMemo(() => new Set(chats.map(c => c.sessionId)), [chats]);

  async function loadFirst() {
    setInitialLoading(true);
    try {
      const ceil = new Date().toISOString();
      setCeiling(ceil);
      const res = await listChatsPage(0, pageSize, ceil);
      setChats(res.content);
      setPage(1);
      setHasMore(!res.last);
      setTotal(res.totalElements ?? 0);
      setTotalPages(res.totalPages ?? 0);
    } catch {
      setChats([]); setPage(0); setHasMore(false); setTotal(0); setTotalPages(0);
    } finally {
      setInitialLoading(false);
    }
  }

  async function loadMore() {
    if (loadingMoreRef.current || loadingMore || !hasMore || !ceiling) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const res = await listChatsPage(page, pageSize, ceiling);
      const next = res.content.filter(c => !seenIds.has(c.sessionId));
      setChats(prev => [...prev, ...next]);
      setPage(p => p + 1);
      setHasMore(!res.last);
      setTotal(res.totalElements ?? total);
      setTotalPages(res.totalPages ?? totalPages);
    } catch {
      setHasMore(false);
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }

  async function refreshFirst() {
    setChats([]); setPage(0); setHasMore(true);
    setTotal(0); setTotalPages(0); setCeiling(null);
    await loadFirst();
  }

  const didMountRef = useRef(false);
  useEffect(() => {
    if (!didMountRef.current) { didMountRef.current = true; return; }
    if (typeof refreshKey !== "undefined") void refreshFirst();
  }, [refreshKey]);

  useEffect(() => {
    const handler = (evt: Event) => {
      const detail = (evt as CustomEvent<any>).detail;
      if (!detail?.sessionId) return;
      const sid = String(detail.sessionId);
      setChats(prev => {
        const ix = prev.findIndex(c => c.sessionId === sid);
        const shouldMoveToTop = typeof detail.lastMessage === "string";
        if (ix === -1) {
          if (!shouldMoveToTop) return prev;
          const injected: ChatRow = {
            sessionId: sid,
            id: -1,
            title: detail.title ?? "New Chat",
            lastMessage: detail.lastMessage ?? "",
            createdAt: new Date().toISOString(),
            updatedAt: detail.updatedAt ?? new Date().toISOString(),
          };
          return [injected, ...prev];
        }
        const cur = prev[ix];
        const patched: ChatRow = {
          ...cur,
          lastMessage: detail.lastMessage ?? cur.lastMessage,
          title: detail.title ?? cur.title,
          updatedAt: detail.updatedAt ?? cur.updatedAt,
        };
        const rest = prev.filter((_, i) => i !== ix);
        return shouldMoveToTop ? [patched, ...rest] : [...prev.slice(0, ix), patched, ...prev.slice(ix + 1)];
      });
    };
    window.addEventListener("chats:refresh", handler as EventListener);
    return () => window.removeEventListener("chats:refresh", handler as EventListener);
  }, []);

  useEffect(() => {
    const rootEl = scrollRef.current, sentinel = sentinelRef.current;
    if (!rootEl || !sentinel) return;
    const hasOverflow = rootEl.scrollHeight - rootEl.clientHeight > 8;
    if (!hasOverflow) return;
    const io = new IntersectionObserver((entries) => {
      const entry = entries[0];
      if (entry?.isIntersecting) void loadMore();
    }, { root: rootEl, rootMargin: "96px 0px", threshold: 0.01 });
    io.observe(sentinel);
    return () => io.disconnect();
  }, [chats.length, page, hasMore, ceiling]);

  function decTotal(count: number) {
    setTotal(prev => {
      const next = Math.max(0, prev - count);
      setTotalPages(Math.max(1, Math.ceil(next / pageSize)));
      return next;
    });
  }

  return {
    chats, page, hasMore, total, totalPages,
    initialLoading, loadingMore,
    scrollRef, sentinelRef,
    loadMore, refreshFirst, setChats,
    decTotal,
  };
}
