import { useState } from "react";
import { deleteChatsBatch } from "../../data/chatApi";
import type { ChatRow } from "../../types/chat";
import { useMultiSelect } from "../../hooks/useMultiSelect";
import { useChatsPager } from "../../hooks/useChatsPager";
import SidebarHeader from "./SidebarHeader";
import SidebarListItem from "./SidebarListItem";
import AccountPanel from "./AccountPanel";

const PAGE_SIZE = 10;

type Props = {
  onOpen: (id: string) => Promise<void>;
  onNew: () => Promise<void>;
  refreshKey?: number;
  activeId?: string;
  onHideSidebar?: () => void;
  onCancelSessions?: (ids: string[]) => Promise<void>;
};

export default function ChatSidebar({
  onOpen,
  onNew,
  refreshKey,
  activeId,
  onHideSidebar,
  onCancelSessions,
}: Props) {
  const {
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
    setChats,
    decTotal,
  } = useChatsPager(PAGE_SIZE, refreshKey);

  const [isEditing, setIsEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [newPending, setNewPending] = useState(false);

  const allIds = chats.map((c) => c.sessionId);
  const { selected, setSelected, allSelected, toggleOne, toggleAll } =
    useMultiSelect(allIds);

  async function handleNew() {
    if (newPending) return;
    setNewPending(true);
    try {
      await onNew();
    } finally {
      setNewPending(false);
    }
  }

  async function onDeleteSelected(): Promise<void> {
    const count = selected.size;
    if (!count || deleting) return;

    const isAll = count === chats.length;
    const ok = window.confirm(
      isAll
        ? `Delete ALL ${count} chats? This cannot be undone.`
        : `Delete ${count} selected chat${count > 1 ? "s" : ""}?`,
    );
    if (!ok) return;

    const ids = [...selected];
    try {
      await onCancelSessions?.(ids);
      await Promise.resolve();
    } catch {}

    const deletingActive = activeId ? selected.has(activeId) : false;
    const fallback = chats.find((c) => !selected.has(c.sessionId))?.sessionId;

    setDeleting(true);
    try {
      const deleted = await deleteChatsBatch(ids);
      if (!deleted.length) return;
      setChats((prev) => prev.filter((c) => !deleted.includes(c.sessionId)));
      decTotal(deleted.length);
      setSelected(new Set());
      setIsEditing(false);

      if (deletingActive && fallback) {
        void onOpen(fallback);
      }
    } finally {
      setDeleting(false);
    }
  }

  return (
    <aside className="w-full md:w-72 h-full border-r bg-white p-0 flex flex-col">
      <SidebarHeader
        isEditing={isEditing}
        setIsEditing={(v) => {
          setIsEditing(v);
          setSelected(new Set());
        }}
        newPending={newPending}
        onNew={handleNew}
        onHideSidebar={onHideSidebar}
        selectedCount={selected.size}
        deleting={deleting}
        onDelete={onDeleteSelected}
      />

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-2 overscroll-contain"
        style={{ WebkitOverflowScrolling: "touch" }}
      >
        {initialLoading && (
          <div className="px-2 py-1 text-xs text-gray-500">Loading…</div>
        )}

        <ul className="space-y-1">
          {chats.map((c: ChatRow) => (
            <SidebarListItem
              key={c.sessionId}
              c={c}
              isActive={activeId === c.sessionId}
              isEditing={isEditing}
              isChecked={selected.has(c.sessionId)}
              onToggle={() => toggleOne(c.sessionId)}
              onOpen={() => void onOpen(c.sessionId)}
            />
          ))}
        </ul>

        <div className="h-6" ref={sentinelRef} />

        {hasMore && (
          <div className="px-2 pb-2">
            <button
              className={`w-full text-xs px-3 py-1 rounded border ${loadingMore ? "opacity-50 cursor-wait" : ""}`}
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

      <div className="border-t px-3 py-2 text-[11px] text-gray-500">
        <span className="uppercase tracking-wide">Chats</span>{" "}
        <span className="text-gray-400">
          ({chats.length}
          {total ? `/${total}` : ""} • page {Math.max(page, 1)} of{" "}
          {Math.max(totalPages || 1, 1)})
        </span>
        {isEditing && (
          <label className="ml-2 text-[11px]">
            <input
              type="checkbox"
              className="mr-1 align-middle"
              checked={allSelected}
              onChange={toggleAll}
            />
            Select all
          </label>
        )}
      </div>

      <div className="border-t">
        <AccountPanel />
      </div>
    </aside>
  );
}
