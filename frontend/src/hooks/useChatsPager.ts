// frontend/src/file_read/hooks/useChatsPager.ts
import { useEffect, useMemo, useRef, useState } from "react";
import { listChatsPage } from "../data/chatApi";
import type { ChatRow } from "../types/chat";
import { getAdminState } from "../api/admins";
import {
  adminListAllChatsPage,
  adminListMineChatsPage,
  getAdminChatScope,
  type AdminChatScope,
} from "./adminChatsApi";

type PageResp = {
  content: ChatRow[];
  totalElements: number;
  totalPages: number;
  last: boolean;
};

type PageFetcher = (
  page: number,
  size: number,
  ceiling?: string,
) => Promise<PageResp>;

export function useChatsPager(pageSize = 10, refreshKey?: number) {
  const [chats, setChats] = useState<ChatRow[]>([]);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [ceiling, setCeiling] = useState<string | null>(null);
  const [initialLoading, setInitialLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const loadingMoreRef = useRef(false);

  const seenIds = useMemo(
    () => new Set(chats.map((c) => c.sessionId)),
    [chats],
  );

  // Choose which endpoint to use based on admin + scope
  function pickFetcher(
    adminFlag: boolean | null,
    scope: AdminChatScope,
  ): PageFetcher {
    if (!adminFlag) return listChatsPage; // not admin → regular endpoint
    return scope === "all" ? adminListAllChatsPage : adminListMineChatsPage;
  }

  async function ensureIsAdmin(): Promise<boolean> {
    if (isAdmin !== null) return isAdmin;
    try {
      const s = await getAdminState();
      const flag = !!s.isAdmin;
      setIsAdmin(flag);
      return flag;
    } catch {
      setIsAdmin(false);
      return false;
    }
  }

  // Return a valid ISO ceiling or undefined (never an empty string)
  function ensureCeiling(nowIfMissing = false): string | undefined {
    if (ceiling) return ceiling;
    if (nowIfMissing) {
      const c = new Date().toISOString();
      setCeiling(c);
      return c;
    }
    return undefined;
  }

  async function fetchPage(pageNum: number, replace: boolean) {
    const adminFlag = await ensureIsAdmin();
    const scope = getAdminChatScope();
    const fetcher = pickFetcher(adminFlag, scope);

    // On replace, take a fresh pagination watermark
    const c = replace ? new Date().toISOString() : ensureCeiling(true);
    if (replace && c) setCeiling(c);

    let res: PageResp;
    try {
      res = await fetcher(pageNum, pageSize, c);
    } catch (e: any) {
      // If "all" is not allowed (403), fallback to "mine" (admin view), then to user view
      const isForbidden = e?.status === 403 || e?.statusCode === 403;
      if (scope === "all" && isForbidden) {
        try {
          res = await adminListMineChatsPage(pageNum, pageSize, c);
        } catch {
          res = await listChatsPage(pageNum, pageSize, c);
        }
      } else {
        throw e;
      }
    }

    if (replace) {
      setChats(res.content);
      setPage(1);
    } else {
      const next = res.content.filter((r) => !seenIds.has(r.sessionId));
      setChats((prev) => [...prev, ...next]);
      setPage((p) => p + 1);
    }
    setHasMore(!res.last);
    setTotal(res.totalElements ?? 0);
    setTotalPages(res.totalPages ?? 0);
  }

  async function loadFirst() {
    setInitialLoading(true);
    try {
      await fetchPage(0, true);
    } catch {
      setChats([]);
      setPage(0);
      setHasMore(false);
      setTotal(0);
      setTotalPages(0);
    } finally {
      setInitialLoading(false);
    }
  }

  async function loadMore() {
    if (loadingMoreRef.current || loadingMore || !hasMore) return;

    // If ceiling isn't established (rare), bootstrap first page
    if (!ceiling) {
      await loadFirst();
      return;
    }

    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      await fetchPage(page, false);
    } catch {
      setHasMore(false);
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }

  async function refreshFirst() {
    setChats([]);
    setPage(0);
    setHasMore(true);
    setTotal(0);
    setTotalPages(0);
    setCeiling(null);
    await loadFirst();
  }

  // Hydrate when auth is ready
  useEffect(() => {
    const onAuthReady = () => {
      void refreshFirst();
    };
    window.addEventListener("auth:ready", onAuthReady as EventListener);
    return () =>
      window.removeEventListener("auth:ready", onAuthReady as EventListener);
  }, []);

  // React to admin scope changes
  useEffect(() => {
    const onScopeChange = () => {
      void refreshFirst();
    };
    window.addEventListener("admin:scope", onScopeChange as EventListener);
    return () =>
      window.removeEventListener("admin:scope", onScopeChange as EventListener);
  }, []);

  // External refresh trigger
  const didMountRef = useRef(false);
  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      return;
    }
    if (typeof refreshKey !== "undefined") void refreshFirst();
  }, [refreshKey]);

  // Live updates for a specific chat (retitle / lastMessage)
  useEffect(() => {
    const handler = (evt: Event) => {
      const detail = (evt as CustomEvent<any>).detail;
      if (!detail?.sessionId) return;
      const sid = String(detail.sessionId);

      setChats((prev) => {
        const ix = prev.findIndex((c) => c.sessionId === sid);
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
        return shouldMoveToTop
          ? [patched, ...rest]
          : [...prev.slice(0, ix), patched, ...prev.slice(ix + 1)];
      });
    };

    window.addEventListener("chats:refresh", handler as EventListener);
    return () =>
      window.removeEventListener("chats:refresh", handler as EventListener);
  }, []);

  // Infinite scroll
  useEffect(() => {
    const rootEl = scrollRef.current;
    const sentinel = sentinelRef.current;
    if (!rootEl || !sentinel) return;

    const hasOverflow = rootEl.scrollHeight - rootEl.clientHeight > 8;
    if (!hasOverflow) return;

    const io = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry?.isIntersecting) void loadMore();
      },
      { root: rootEl, rootMargin: "96px 0px", threshold: 0.01 },
    );

    io.observe(sentinel);
    return () => io.disconnect();
  }, [chats.length, page, hasMore, ceiling]);

  function decTotal(count: number) {
    setTotal((prev) => {
      const next = Math.max(0, prev - count);
      setTotalPages(Math.max(1, Math.ceil(next / pageSize)));
      return next;
    });
  }

  return {
    chats,
    page,
    hasMore,
    total,
    totalPages,
    initialLoading,
    loadingMore,
    scrollRef,
    sentinelRef,
    loadMore,
    refreshFirst,
    setChats,
    decTotal,
  };
}
