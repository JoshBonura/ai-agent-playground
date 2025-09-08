import { useState } from "react";
import ChatContainer from "../components/ChatContainer";
import ChatSidebar from "../components/ChatSidebar/ChatSidebar";
import { useChatStream } from "../hooks/useChatStream";
import { useSidebar } from "../hooks/useSidebar";
import { useToast } from "../hooks/useToast";
import DesktopHeader from "../components/DesktopHeader";
import MobileDrawer from "../components/MobileDrawer";
import Toast from "../shared/ui/Toast";
import { createChat, deleteMessagesBatch } from "../data/chatApi";

// NEW: settings panel
import SettingsPanel from "../components/SettingsPanel";
import KnowledgePanel from "../components/KnowledgePanel";
import SearchTester from "../components/SearchTester";

const LS_KEY = "lastSessionId";

export default function AgentRunner() {
  const chat = useChatStream();
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [autoFollow, setAutoFollow] = useState(true);
  const { toast, show } = useToast();
  const { sidebarOpen, setSidebarOpen, openMobileDrawer, closeMobileDrawer } = useSidebar();

  // NEW: settings modal
  const [showSettings, setShowSettings] = useState(false);

  // ⛔ Removed the mount-time bootstrap that fetched chats and loaded history.

  async function newChat(): Promise<void> {
    const id = crypto.randomUUID();
    chat.setSessionId(id);
    try { await createChat(id, "New Chat"); } catch {}
    localStorage.setItem(LS_KEY, id);
    setRefreshKey((k) => k + 1);
    chat.setInput("");
    chat.clearMetrics?.();
    await refreshFollow();
  }

  async function openSession(id: string): Promise<void> {
    if (!id) return;
    await chat.loadHistory(id);
    localStorage.setItem(LS_KEY, id);
    chat.setInput("");
    chat.clearMetrics?.();
    await refreshFollow();
  }

  // --- TWO REFRESH HELPERS ---

  // 1) Follow-to-bottom refresh (normal)
  async function refreshFollow() {
    const sid = chat.sessionIdRef.current;
    if (!sid) return;
    setAutoFollow(true);
    await chat.loadHistory(sid);
    const el = document.getElementById("chat-scroll-container");
    if (el) el.scrollTop = el.scrollHeight;
  }

async function handleCancelSessions(ids: string[]) {
  if (!ids?.length) return;

  const currentId = chat.sessionIdRef.current || "";
  const deletingActive = currentId && ids.includes(currentId);

  if (deletingActive) {
    // clear out current session instead of making a new one
    chat.setSessionId("");
    chat.setInput("");
    chat.clearMetrics?.();
    // optional: clear messages too
    chat.reset();
    localStorage.removeItem(LS_KEY);
  }

  setRefreshKey((k) => k + 1);
  try { window.dispatchEvent(new CustomEvent("chats:refresh")); } catch {}
}


  // 2) Preserve-scroll refresh (use for deletions, etc.)
  async function refreshPreserve() {
    const sid = chat.sessionIdRef.current;
    if (!sid) return;
    const el = document.getElementById("chat-scroll-container");
    const prevTop = el?.scrollTop ?? 0;
    const prevHeight = el?.scrollHeight ?? 0;

    setAutoFollow(false);
    await chat.loadHistory(sid);

    requestAnimationFrame(() => {
      if (el) {
        const newHeight = el.scrollHeight;
        el.scrollTop = prevTop + (newHeight - prevHeight);
      }
      setAutoFollow(true);
    });
  }

  // Delete by clientId(s). Immediate UI remove; API delete only for server-backed msgs.
  async function handleDeleteMessages(clientIds: string[]) {
    const sid = chat.sessionIdRef.current;
    if (!sid || !clientIds?.length) return;

    const current = chat.messages;
    const toDelete = new Set(clientIds);

    const serverIds = current
      .filter((m: any) => toDelete.has(m.id) && m.serverId != null)
      .map((m: any) => m.serverId as number);

    const remaining = current.filter((m) => !toDelete.has(m.id));

    // Optimistic local state
    if ((chat as any).setMessagesForSession) {
      (chat as any).setMessagesForSession(sid, () => remaining);
    }

    try {
      if (serverIds.length) {
        await deleteMessagesBatch(sid, serverIds);
      }

      await refreshPreserve();

      setRefreshKey((k) => k + 1);
      try { window.dispatchEvent(new CustomEvent("chats:refresh")); } catch {}

      show("Message deleted");
    } catch {
      show("Failed to delete message");
      await chat.loadHistory(sid);
      setRefreshKey((k) => k + 1);
    }
  }

  return (
    <div className="h-screen w-full flex bg-gray-50">
      {sidebarOpen && (
        <div className="hidden md:flex h-full">
          <ChatSidebar
            onOpen={openSession}
            onNew={newChat}
            refreshKey={refreshKey}
            activeId={chat.sessionIdRef.current}
            onHideSidebar={() => setSidebarOpen(false)}
            onCancelSessions={handleCancelSessions}
          />
        </div>
      )}

      <MobileDrawer
        onOpenSession={openSession}
        onNewChat={newChat}
        refreshKey={refreshKey}
        activeId={chat.sessionIdRef.current}
        openMobileDrawer={openMobileDrawer}
        closeMobileDrawer={closeMobileDrawer}
      />
      <div className="md:hidden h-14 shrink-0" />

      <div className="flex-1 min-w-0 flex flex-col">
        <DesktopHeader
          sidebarOpen={sidebarOpen}
          onShowSidebar={() => setSidebarOpen(true)}
        />

        <div className="px-3 md:px-6 pt-2">
          <div className="mx-auto max-w-3xl md:max-w-4xl flex justify-end gap-2">
            <button
              className="text-xs px-3 py-1.5 rounded border bg-white hover:bg-gray-50"
              onClick={() => setShowKnowledge(true)}
              title="Open Knowledge"
            >
              Knowledge
            </button>
            <button
              className="text-xs px-3 py-1.5 rounded border bg-white hover:bg-gray-50"
              onClick={() => setShowSettings(true)}
              title="Open Settings"
            >
              Settings
            </button>
          </div>
          <div className="mx-auto max-w-3xl md:max-w-4xl mt-2">
            <SearchTester />
          </div>
        </div>

        <div className="flex-1 min-h-0">
          <div className="h-full px-3 md:px-6">
            <div className="h-full w-full mx-auto max-w-3xl md:max-w-4xl relative">
              {/* Note: add id on the scroll container wrapper for refresh helpers */}
              <div id="chat-scroll-container" className="h-full">
                <ChatContainer
                  messages={chat.messages}
                  input={chat.input}
                  setInput={chat.setInput}
                  loading={chat.loading}
                  queued={chat.queued}
                  send={chat.send}
                  stop={chat.stop}
                  runMetrics={chat.runMetrics}
                  runJson={chat.runJson}
                  onRefreshChats={() => {}}
                  onDeleteMessages={handleDeleteMessages}
                  autoFollow={autoFollow}
                  sessionId={chat.sessionIdRef.current} // enables per-chat uploads
                />
              </div>
              <Toast message={toast} />
            </div>
          </div>
        </div>
      </div>

      {/* NEW: settings modal */}
      {showSettings && (
        <SettingsPanel
          sessionId={chat.sessionIdRef.current}
          onClose={() => setShowSettings(false)}
        />
      )}
      {showKnowledge && (
        <KnowledgePanel
          sessionId={chat.sessionIdRef.current}
          onClose={() => setShowKnowledge(false)}
          toast={show}
        />
      )}
    </div>
  );
}
