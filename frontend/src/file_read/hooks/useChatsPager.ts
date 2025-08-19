import { useEffect, useMemo, useRef, useState } from "react";
import { listChatsPage } from "../hooks/data/chatApi";
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

  // external refreshes
  useEffect(() => { void refreshFirst(); /* eslint-disable-next-line */ }, [refreshKey]);
  useEffect(() => {
    const onRefresh = () => void refreshFirst();
    window.addEventListener("chats:refresh", onRefresh);
    return () => window.removeEventListener("chats:refresh", onRefresh);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // infinite scroll
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chats.length, page, hasMore, ceiling]);

  return {
    // state
    chats, page, hasMore, total, totalPages,
    initialLoading, loadingMore,
    // refs
    scrollRef, sentinelRef,
    // actions
    loadMore, refreshFirst, setChats,
  };
}
