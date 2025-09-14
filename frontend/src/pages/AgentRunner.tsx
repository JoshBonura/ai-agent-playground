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
import { createChat, deleteMessagesBatch } from "../data/chatApi";
import SettingsPanel from "../components/SettingsPanel";
import KnowledgePanel from "../components/KnowledgePanel";
import { useAuth } from "../auth/AuthContext";

// Model picker + API
import ModelPicker from "../components/ModelPicker/ModelPicker";
import { getModelHealth } from "../api/models";
import type { Attachment } from "../types/chat";

const LS_KEY = "lastSessionId";

export default function AgentRunner() {
  const chat = useChatStream();
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [autoFollow, setAutoFollow] = useState(true);
  const { toast, show } = useToast();
  const { sidebarOpen, setSidebarOpen, openMobileDrawer, closeMobileDrawer } = useSidebar();
  const [showSettings, setShowSettings] = useState(false);

  // LM-Studio–style model picker
  const [showModelPicker, setShowModelPicker] = useState(false);

  // Auth → refresh chat list after /auth/me resolves
  const { user, loading } = useAuth();
  useEffect(() => {
    if (!loading && user) setRefreshKey((k) => k + 1);
  }, [loading, user]);

  // ---- Model health (polled) ----
  const [health, setHealth] = useState<{ ok: boolean; loaded: boolean; config: any } | null>(null);
  const modelLoaded = !!health?.loaded;
  const modelName =
    (health?.config?.config?.modelPath || health?.config?.modelPath || "")
      .split(/[\\/]/)
      .pop() || null;

  useEffect(() => {
    let alive = true;
    let t: any;
    const poll = async () => {
      try {
        const h = await getModelHealth(); // GET /api/models/health
        if (alive) setHealth(h);
      } catch {
        if (alive) setHealth({ ok: false, loaded: false, config: null });
      } finally {
        t = setTimeout(poll, 4000);
      }
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  // Guard send if model not loaded (mirrors backend gating) — ACCEPT & FORWARD ARGUMENTS
  async function safeSend(text?: string, attachments?: Attachment[]) {
    if (!modelLoaded) {
      show("Select & load a model to start chatting.");
      setShowModelPicker(true);
      return;
    }
    // prefer explicit text from composer; fallback to current input
    const t = (text ?? chat.input ?? "").trim();
    if (!t && !(attachments && attachments.length)) return;

    try {
      await chat.send(t, attachments);
    } catch (e: any) {
      const msg =
        e?.message === "MODEL_NOT_LOADED"
          ? "Model not loaded. Select a model to start."
          : e?.message || "Unable to send. Is a model loaded?";
      show(msg);
    }
  }

  // Settings/Knowledge global events
  useEffect(() => {
    const openSettings = () => setShowSettings(true);
    const openKnowledge = () => setShowKnowledge(true);
    const openCustomize = () => setShowKnowledge(true);
    window.addEventListener("open:settings", openSettings);
    window.addEventListener("open:knowledge", openKnowledge);
    window.addEventListener("open:customize", openCustomize);
    return () => {
      window.removeEventListener("open:settings", openSettings);
      window.removeEventListener("open:knowledge", openKnowledge);
      window.removeEventListener("open:customize", openCustomize);
    };
  }, []);

  // ----- Chat helpers -----
  async function newChat(): Promise<void> {
    const id = crypto.randomUUID();
    chat.setSessionId(id);
    try {
      await createChat(id, "New Chat");
    } catch {}
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

  async function refreshFollow() {
    const sid = chat.sessionIdRef.current;
    if (!sid) return;
    setAutoFollow(true);
    await chat.loadHistory(sid);
    const el = document.getElementById("chat-scroll-container");
    if (el) el.scrollTop = el.scrollHeight;
  }

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

  async function handleCancelSessions(ids: string[]) {
    if (!ids?.length) return;
    const currentId = chat.sessionIdRef.current || "";
    const deletingActive = currentId && ids.includes(currentId);
    if (deletingActive) {
      chat.setSessionId("");
      chat.setInput("");
      chat.clearMetrics?.();
      chat.reset();
      localStorage.removeItem(LS_KEY);
    }
    setRefreshKey((k) => k + 1);
    try {
      window.dispatchEvent(new CustomEvent("chats:refresh"));
    } catch {}
  }

  async function handleDeleteMessages(clientIds: string[]) {
    const sid = chat.sessionIdRef.current;
    if (!sid || !clientIds?.length) return;
    const current = chat.messages;
    const toDelete = new Set(clientIds);
    const serverIds = current
      .filter((m: any) => toDelete.has(m.id) && m.serverId != null)
      .map((m: any) => m.serverId as number);
    const remaining = current.filter((m) => !toDelete.has(m.id));
    if ((chat as any).setMessagesForSession) {
      (chat as any).setMessagesForSession(sid, () => remaining);
    }
    try {
      if (serverIds.length) {
        await deleteMessagesBatch(sid, serverIds);
      }
      await refreshPreserve();
      setRefreshKey((k) => k + 1);
      try {
        window.dispatchEvent(new CustomEvent("chats:refresh"));
      } catch {}
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
          modelLoaded={modelLoaded}
          modelName={modelName}
          busy={false}
          onOpenModelPicker={() => setShowModelPicker(true)}
          onEjectModel={async () => {
            try {
              await fetch("/api/models/unload", { method: "POST", credentials: "include" });
              setHealth((h) =>
                h ? { ...h, loaded: false } : { ok: true, loaded: false, config: null },
              );
            } catch {
              show("Failed to unload model");
            }
          }}
        />

        {!modelLoaded && (
          <div className="px-3 md:px-6 mt-2">
            <div className="mx-auto max-w-3xl md:max-w-4xl">
              <div className="rounded-lg border bg-amber-50 text-amber-900 text-sm px-3 py-2">
                No model is loaded. Click{" "}
                <button
                  className="ml-1 inline-flex items-center text-xs px-2 py-1 rounded border hover:bg-amber-100"
                  onClick={() => setShowModelPicker(true)}
                >
                  Select a model to load
                </button>{" "}
                to start chatting.
              </div>
            </div>
          </div>
        )}

        <div className="flex-1 min-h-0">
          <div className="h-full px-3 md:px-6">
            <div className="h-full w-full mx-auto max-w-3xl md:max-w-4xl relative">
              <div id="chat-scroll-container" className="h-full">
                <ChatContainer
                  messages={chat.messages}
                  input={chat.input}
                  setInput={chat.setInput}
                  loading={chat.loading}
                  queued={chat.queued}
                  send={safeSend}               
                  stop={chat.stop}
                  runMetrics={chat.runMetrics}
                  runJson={chat.runJson}
                  onRefreshChats={() => {}}
                  onDeleteMessages={handleDeleteMessages}
                  autoFollow={autoFollow}
                  sessionId={chat.sessionIdRef.current}
                />
              </div>
              <Toast message={toast} />
            </div>
          </div>
        </div>
      </div>

      {showModelPicker && (
        <ModelPicker
          open={showModelPicker}
          onClose={() => setShowModelPicker(false)}
          onLoaded={async () => {
            try {
              const h = await getModelHealth();
              setHealth(h);
            } catch {}
          }}
        />
      )}

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
