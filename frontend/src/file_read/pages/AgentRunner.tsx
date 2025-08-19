// frontend/src/file_read/pages/AgentRunner.tsx
import { useEffect, useState } from "react";
import ChatContainer from "../components/ChatContainer";
import ChatSidebar from "../components/ChatSidebar/ChatSidebar";
import { useChatStream } from "../hooks/useChatStream";
import { useSidebar } from "../hooks/useSidebar";
import { useToast } from "../hooks/useToast";
import DesktopHeader from "../components/DesktopHeader";
import MobileDrawer from "../components/MobileDrawer";
import Toast from "../shared/ui/Toast";

// Use a single API layer (services)
import { createChat, listChatsPage, deleteMessagesBatch, enqueuePendingDelete } from "../hooks/data/chatApi";
import { cancelSession } from "../hooks/data/aiApi";

const PAGE_SIZE = 30;
const LS_KEY = "lastSessionId";

export default function AgentRunner() {
  const chat = useChatStream();
  const [refreshKey, setRefreshKey] = useState(0);
  const { toast, show } = useToast();
  const { sidebarOpen, setSidebarOpen, openMobileDrawer, closeMobileDrawer } = useSidebar();

  // initial load: open last or most recent session
  useEffect(() => {
    (async () => {
      try {
        const ceil = new Date().toISOString();
        const page = await listChatsPage(0, PAGE_SIZE, ceil);
        const saved = localStorage.getItem(LS_KEY) || "";
        const targetId =
          (saved && page.content.find((c) => c.sessionId === saved)?.sessionId) ||
          page.content[0]?.sessionId ||
          "";
        if (targetId) {
          await chat.loadHistory(targetId);
          localStorage.setItem(LS_KEY, targetId);
        }
      } catch {}
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function newChat(): Promise<void> {
    const id = crypto.randomUUID();
    chat.setSessionId(id);
    try { await createChat(id, "New Chat"); } catch {}
    localStorage.setItem(LS_KEY, id);
    setRefreshKey((k) => k + 1);
    chat.setInput("");
    chat.clearMetrics?.();
  }

  async function openSession(id: string): Promise<void> {
    if (!id) return;
    await chat.loadHistory(id);
    localStorage.setItem(LS_KEY, id);
    chat.setInput("");
    chat.clearMetrics?.();
  }

  // Single, consolidated delete handler (queues while streaming)
  async function handleDeleteMessages(ids: string[]) {
    const sid = chat.sessionIdRef.current;
    if (!sid || !ids?.length) return;

    const numericIds = ids.map(Number).filter(Number.isFinite);

    // If the session is currently streaming, queue + cancel.
    if (chat.loading) {
      try {
        // non-numeric ID likely = in-flight assistant bubble
        const tailAssistant = ids.some((x) => !/^\d+$/.test(x));
        await enqueuePendingDelete(sid, {
          messageIds: numericIds.length ? numericIds : undefined,
          tailAssistant,
        });
        await cancelSession(sid); // stop stream; backend applies pending on next append
        show("Delete queued; will apply as soon as the run settles.");
      } catch {
        show("Failed to queue delete");
      }
      return;
    }

    // Not streaming: perform immediately
    if (!numericIds.length) {
      show("Nothing to delete yet");
      return;
    }
    try {
      await deleteMessagesBatch(sid, numericIds);
      await chat.loadHistory(sid);
      setRefreshKey((k) => k + 1);
      show("Message deleted");
    } catch {
      show("Failed to delete message");
    }
  }

  return (
    <div className="h-screen w-full flex bg-gray-50">
      {/* Desktop sidebar */}
      {sidebarOpen && (
        <div className="hidden md:flex h-full">
          <ChatSidebar
            onOpen={openSession}
            onNew={newChat}
            refreshKey={refreshKey}
            activeId={chat.sessionIdRef.current}
            onHideSidebar={() => setSidebarOpen(false)}
          />
        </div>
      )}

      {/* Mobile controls */}
      <MobileDrawer
        onOpenSession={openSession}
        onNewChat={newChat}
        refreshKey={refreshKey}
        activeId={chat.sessionIdRef.current}
        openMobileDrawer={openMobileDrawer}
        closeMobileDrawer={closeMobileDrawer}
      />
      <div className="md:hidden h-14 shrink-0" />

      {/* Right column */}
      <div className="flex-1 min-w-0 flex flex-col">
        <DesktopHeader sidebarOpen={sidebarOpen} onShowSidebar={() => setSidebarOpen(true)} />
        <div className="flex-1 min-h-0">
          <div className="h-full px-3 md:px-6">
            <div className="h-full w-full mx-auto max-w-3xl md:max-w-4xl relative">
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
                onRefreshChats={() => setRefreshKey((k) => k + 1)}
                onDeleteMessages={handleDeleteMessages}
              />
              <Toast message={toast} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
