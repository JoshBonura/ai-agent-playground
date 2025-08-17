// frontend/src/file_read/pages/AgentRunner.tsx
import ChatContainer from "../components/ChatContainer";
import ChatSidebar from "../components/ChatSidebar";
import { useEffect, useState } from "react";
import { useChatStream } from "../hooks/useChatStream";
import { appendMessage, updateChatLast } from "../services/chatApi";
import { firstLineSmart } from "../utils/text";
import { PanelLeftOpen } from "lucide-react";

export default function AgentRunner() {
  const chat = useChatStream();
  const [refreshKey, setRefreshKey] = useState(0);

  // Sidebar open/close (visible by default on desktop)
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768);

  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth >= 768) setSidebarOpen(true); // pin on desktop
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // ---- New Chat ----
  async function newChat(): Promise<void> {
    const prevSessionId = chat.sessionIdRef.current;
    const wasStreaming = chat.loading;
    const pending = (chat as any).snapshotPendingAssistant?.() ?? "";

    if (wasStreaming) {
      try { await chat.stop(); } catch {}
      if (pending && pending.trim() && prevSessionId) {
        try {
          await appendMessage(prevSessionId, "assistant", pending);
          await updateChatLast(prevSessionId, pending, firstLineSmart(pending));
        } catch (e) {
          console.warn("persist pending assistant failed:", e);
        }
      }
    }

    chat.reset();
    const id = crypto.randomUUID();
    chat.setSessionId(id);
    setRefreshKey((k) => k + 1);
  }

  // ---- Open existing session ----
  async function openSession(id: string): Promise<void> {
    if (!id) {
      chat.reset();
      return;
    }
    try { await chat.stop(); } catch {}
    await chat.loadHistory(id);
  }

  // Mobile drawer helpers
  const openMobileDrawer = () => {
    document.getElementById("mobile-drawer")?.classList.remove("hidden");
    document.getElementById("mobile-backdrop")?.classList.remove("hidden");
    document.body.style.overflow = "hidden";
  };
  const closeMobileDrawer = () => {
    document.getElementById("mobile-drawer")?.classList.add("hidden");
    document.getElementById("mobile-backdrop")?.classList.add("hidden");
    document.body.style.overflow = "";
  };

  // Optional: Ctrl+B to toggle on desktop
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && (e.key === "b" || e.key === "B")) {
        e.preventDefault();
        setSidebarOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="h-screen w-full flex bg-gray-50">
      {/* Desktop left rail */}
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

      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 bg-white border-b">
        <div className="h-14 flex items-center justify-between px-3">
          <button
            className="inline-flex items-center justify-center h-9 w-9 rounded-lg border hover:bg-gray-50"
            onClick={openMobileDrawer}
            aria-label="Open sidebar"
            title="Open sidebar"
          >
            <PanelLeftOpen className="w-4 h-4" />
          </button>
          <div className="font-semibold">Local AI Model</div>
          <div className="w-9" />
        </div>
      </div>

      {/* Mobile drawer */}
      <div
        id="mobile-backdrop"
        className="md:hidden fixed inset-0 z-40 bg-black/40 hidden"
        onClick={closeMobileDrawer}
      />
      <aside
        id="mobile-drawer"
        role="dialog"
        aria-modal="true"
        className="md:hidden fixed inset-y-0 left-0 z-50 w-80 max-w-[85vw] bg-white border-r shadow-xl hidden animate-[slideIn_.2s_ease-out]"
      >
        <div className="h-14 flex items-center justify-between px-3 border-b">
          <div className="font-medium">Chats</div>
          <button
            className="h-9 w-9 inline-flex items-center justify-center rounded-lg border hover:bg-gray-50"
            onClick={closeMobileDrawer}
            aria-label="Close sidebar"
          >
            <span className="rotate-45 text-xl leading-none">+</span>
          </button>
        </div>
        <ChatSidebar
          onOpen={async (id) => {
            await openSession(id);
            closeMobileDrawer();
          }}
          onNew={async () => {
            await newChat();
            closeMobileDrawer();
          }}
          refreshKey={refreshKey}
          activeId={chat.sessionIdRef.current}
        />
      </aside>
      <style>{`@keyframes slideIn{from{transform:translateX(-12px);opacity:.0}to{transform:translateX(0);opacity:1}}`}</style>

      {/* Right/main column */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Spacer under fixed mobile bar */}
        <div className="md:hidden h-14 shrink-0" />

        {/* Desktop header with Show button when hidden */}
        <div className="hidden md:flex h-14 shrink-0 items-center justify-between px-4 border-b bg-white">
          <div className="flex items-center gap-2">
            {!sidebarOpen && (
              <button
                className="h-9 w-9 inline-flex items-center justify-center rounded-lg border hover:bg-gray-50"
                onClick={() => setSidebarOpen(true)}
                aria-label="Show sidebar"
                title="Show sidebar"
              >
                <PanelLeftOpen className="w-4 h-4" />
              </button>
            )}
            <div className="font-semibold">Local AI Model</div>
          </div>
          <div />
        </div>

        {/* Content fills remaining height */}
        <div className="flex-1 min-h-0">

          {/* Chat area — centered, width-capped like ChatGPT */}
          <div className="h-full px-3 md:px-6">
            <div className="h-full w-full mx-auto max-w-3xl md:max-w-4xl">
              <ChatContainer
                messages={chat.messages}
                input={chat.input}
                setInput={chat.setInput}
                loading={chat.loading}
                send={chat.send}
                stop={chat.stop}
                onRefreshChats={() => setRefreshKey((k) => k + 1)}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
