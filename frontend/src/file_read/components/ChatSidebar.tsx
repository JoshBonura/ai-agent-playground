// frontend/src/file_read/components/ChatSidebar.tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { listChatsPage, deleteChatsBatch } from "../services/chatApi";
import type { ChatRow } from "../types/chat";
import { useMultiSelect } from "../hooks/useMultiSelect";
import { firstLineSmart } from "../utils/text";
import { PanelLeftClose, Plus, Pencil, Trash2 } from "lucide-react";

const PAGE_SIZE = 10;

type Props = {
  onOpen: (id: string) => Promise<void>;
  onNew: () => Promise<void>;
  refreshKey?: number;
  activeId?: string;
  onHideSidebar?: () => void;
};

export default function ChatSidebar({
  onOpen,
  onNew,
  refreshKey,
  activeId,
  onHideSidebar,
}: Props) {
  const [chats, setChats] = useState<ChatRow[]>([]);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [ceiling, setCeiling] = useState<string | null>(null);

  const [initialLoading, setInitialLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [newPending, setNewPending] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const loadingMoreRef = useRef(false);

  const refreshFirst = async () => {
    setChats([]);
    setPage(0);
    setHasMore(true);
    setTotal(0);
    setTotalPages(0);
    setCeiling(null);
    await loadFirst();
  };

  const seenIds = useMemo(() => new Set(chats.map((c) => c.sessionId)), [chats]);

  async function loadFirst() {
    setInitialLoading(true);
    try {
      const ceil = new Date().toISOString();
      setCeiling(ceil);
      const res = await listChatsPage(0, PAGE_SIZE, ceil);
      setChats(res.content);
      setPage(1);
      setHasMore(!res.last);
      setTotal(res.totalElements ?? 0);
      setTotalPages(res.totalPages ?? 0);
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
    if (loadingMoreRef.current || loadingMore || !hasMore || !ceiling) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const res = await listChatsPage(page, PAGE_SIZE, ceiling);
      const next = res.content.filter((c) => !seenIds.has(c.sessionId));
      setChats((prev) => [...prev, ...next]);
      setPage((p) => p + 1);
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

  useEffect(() => {
    void refreshFirst();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  useEffect(() => {
    const onRefresh = () => void refreshFirst();
    window.addEventListener("chats:refresh", onRefresh);
    return () => window.removeEventListener("chats:refresh", onRefresh);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      { root: rootEl, rootMargin: "96px 0px", threshold: 0.01 }
    );

    io.observe(sentinel);
    return () => io.disconnect();
  }, [chats.length, page, hasMore, ceiling]);

  const allIds = chats.map((c) => c.sessionId);
  const { selected, setSelected, allSelected, toggleOne, toggleAll } =
    useMultiSelect(allIds);

  async function onDeleteSelected(): Promise<void> {
    const count = selected.size;
    if (count === 0 || deleting) return;

    const isAll = count === chats.length;
    const ok = window.confirm(
      isAll
        ? `Delete ALL ${count} chats? This cannot be undone.`
        : `Delete ${count} selected chat${count > 1 ? "s" : ""}?`
    );
    if (!ok) return;

    const deletingActive = activeId ? selected.has(activeId) : false;
    const fallback = chats.find((c) => !selected.has(c.sessionId))?.sessionId;

    setDeleting(true);
    try {
      const deleted = await deleteChatsBatch([...selected]);
      if (!deleted.length) return;

      setChats((prev) => prev.filter((c) => !deleted.includes(c.sessionId)));
      setSelected(new Set());
      setIsEditing(false);

      if (deletingActive) {
        if (fallback) void onOpen(fallback);
        else void onOpen("");
      }
    } finally {
      setDeleting(false);
    }
  }

  return (
    <aside className="w-full md:w-72 h-full border-r bg-white p-0 flex flex-col">
      {/* HEADER */}
      <div className="sticky top-0 z-10 bg-white border-b">
        <div className="flex items-center justify-between px-3 py-2">
          <div className="text-[11px] md:text-xs uppercase text-gray-500">
            Chats
          </div>

          <div className="flex items-center gap-2">
            {/* New chat */}
            <button
              className={`h-9 px-3 inline-flex items-center gap-2 justify-center rounded border ${
                newPending ? "opacity-50 cursor-not-allowed" : ""
              }`}
              onClick={async () => {
                if (newPending) return;
                setNewPending(true);
                try {
                  await onNew();
                } finally {
                  setNewPending(false);
                }
              }}
              title="New chat"
              disabled={newPending}
            >
              <Plus className="w-4 h-4" />
              <span className="text-xs md:text-[11px] leading-none">New</span>
            </button>

            {/* Edit toggle */}
            <button
              className="h-9 px-3 inline-flex items-center gap-2 justify-center rounded border"
              onClick={() => {
                setIsEditing((v) => !v);
                setSelected(new Set());
              }}
              aria-pressed={isEditing}
              title={isEditing ? "Exit edit mode" : "Edit chats"}
            >
              <Pencil className="w-4 h-4" />
              <span className="text-xs md:text-[11px] leading-none">
                {isEditing ? "Done" : "Edit"}
              </span>
            </button>

            {/* Hide sidebar (desktop) */}
            {onHideSidebar && (
              <button
                className="hidden md:inline-flex h-9 w-9 items-center justify-center rounded border"
                onClick={onHideSidebar}
                title="Hide sidebar"
                aria-label="Hide sidebar"
              >
                <PanelLeftClose className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* EDIT TOOLBAR (pushes list down) */}
        {isEditing && (
          <div className="px-3 py-2 border-t bg-white flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={() => toggleAll()}
              />
              Select all
            </label>
            <button
              className={`ml-auto inline-flex items-center gap-2 text-sm px-3 py-1 rounded ${
                selected.size && !deleting
                  ? "bg-red-600 text-white"
                  : "bg-gray-200 text-gray-500 cursor-not-allowed"
              }`}
              disabled={selected.size === 0 || deleting}
              onClick={() => void onDeleteSelected()}
              title={selected.size ? "Delete selected chats" : "Select chats to delete"}
            >
              <Trash2 className="w-4 h-4" />
              {deleting ? "Deleting…" : `Delete (${selected.size})`}
            </button>
          </div>
        )}
      </div>

      {/* LIST (scrolling middle) */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-2 overscroll-contain"
        style={{ WebkitOverflowScrolling: "touch" }}
      >
        {initialLoading && (
          <div className="px-2 py-1 text-xs text-gray-500">Loading…</div>
        )}

        <ul className="space-y-1">
          {chats.map((c) => {
            const isActive = activeId === c.sessionId;
            const isChecked = selected.has(c.sessionId);

            const displayTitle =
              (c.title && c.title.trim()) ||
              firstLineSmart(c.lastMessage || "", 48) ||
              "New Chat";

            const preview = c.lastMessage
              ? firstLineSmart(c.lastMessage, 120)
              : "";

            return (
              <li key={c.sessionId}>
                <div
                  className={`w-full flex items-start gap-2 px-2 py-2 rounded ${
                    isActive ? "bg-black text-white" : "hover:bg-gray-50"
                  }`}
                >
                  {isEditing && (
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => toggleOne(c.sessionId)}
                      className="mt-1"
                      aria-label={`Select chat ${displayTitle}`}
                    />
                  )}
                  <button
                    className="text-left flex-1"
                    aria-current={isActive ? "true" : undefined}
                    onClick={() => {
                      if (!isEditing) void onOpen(c.sessionId);
                    }}
                    title={displayTitle}
                  >
                    <div className="font-medium truncate">{displayTitle}</div>
                    {preview && (
                      <div
                        className={`text-xs line-clamp-2 ${
                          isActive ? "text-white/80" : "text-gray-500"
                        }`}
                      >
                        {preview}
                      </div>
                    )}
                    <div className="text-[10px] mt-1 opacity-60">
                      {new Date(c.updatedAt).toLocaleString()}
                    </div>
                  </button>
                </div>
              </li>
            );
          })}
        </ul>

        {/* Load-more sentinel */}
        <div ref={sentinelRef} className="h-6" />

        {/* Manual Load More */}
        {hasMore && (
          <div className="px-2 pb-2">
            <button
              className={`w-full text-xs px-3 py-1 rounded border ${
                loadingMore ? "opacity-50 cursor-wait" : ""
              }`}
              onClick={() => void loadMore()}
              disabled={loadingMore}
              title="Load next page"
            >
              {loadingMore
                ? "Loading…"
                : `Load more (${chats.length}/${total || "?"})`}
            </button>
          </div>
        )}

        {!hasMore && chats.length > 0 && (
          <div className="px-2 py-2 text-[11px] text-gray-400 text-center">
            End of list • showing {chats.length} of {total || chats.length}
          </div>
        )}
      </div>

      {/* FOOTER META (compact, always at bottom) */}
      <div className="border-t px-3 py-2 text-[11px] text-gray-500">
        <span className="uppercase tracking-wide">Chats</span>{" "}
        <span className="text-gray-400">
          ({chats.length}
          {total ? `/${total}` : ""} • page {Math.max(page, 1)} of{" "}
          {Math.max(totalPages || 1, 1)})
        </span>
      </div>
    </aside>
  );
}
