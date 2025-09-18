import { useEffect, useState } from "react";
import { useChatStream } from "../hooks/useChatStream";
import { useSidebar } from "../hooks/useSidebar";
import { useToast } from "../hooks/useToast";
import { createChat, deleteMessagesBatch } from "../data/chatApi";
import { useAuth } from "../auth/AuthContext";
import { getModelHealth } from "../api/models";
import { getJSON } from "../services/http"; // removed postJSON
import type { Attachment } from "../types/chat";
import AgentRunnerView from "./AgentRunnerView";

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

  // ---- Single-runtime health ----
  const [health, setHealth] = useState<{ ok: boolean; loaded: boolean; config: any } | null>(null);
  const singleRuntimeLoaded = !!health?.loaded;
  const singleRuntimeModelName =
    (health?.config?.config?.modelPath || health?.config?.modelPath || "")
      .split(/[\\/]/)
      .pop() || null;

  useEffect(() => {
    let alive = true;
    let t: any;
    const poll = async () => {
      try {
        const h = await getModelHealth();
        if (alive) setHealth(h);
      } catch {
        if (alive) setHealth({ ok: false, loaded: false, config: null });
      } finally {
        t = setTimeout(poll, 40000);
      }
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  // ---- Worker readiness (active+ready) ----
  const [workerActiveReady, setWorkerActiveReady] = useState(false);
  const [workerModelName, setWorkerModelName] = useState<string | null>(null);

  async function refreshWorkerReady() {
    try {
      const info = await getJSON<{ ok: boolean; workers: any[]; active: string | null }>(
        "/api/model-workers/inspect"
      );
      const activeId = info?.active || null;
      const active = info?.workers?.find((w) => w.id === activeId) || null;
      const ready = !!active && active.status === "ready";
      setWorkerActiveReady(ready);
      if (ready && active) {
        const nm = (active.model_path || "").split(/[\\/]/).pop() || active.model_path || "";
        setWorkerModelName(nm || null);
      } else {
        setWorkerModelName(null);
      }
    } catch {
      setWorkerActiveReady(false);
      setWorkerModelName(null);
    }
  }

  useEffect(() => {
    let alive = true;
    let t: any;
    const poll = async () => {
      if (!alive) return;
      await refreshWorkerReady();
      t = setTimeout(poll, 30000);
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  // 👇 Treat either single-runtime OR active worker as “ready”
  const modelLoaded = singleRuntimeLoaded || workerActiveReady;
  const modelName = workerActiveReady ? workerModelName : singleRuntimeModelName;

  // Send message: unified streaming path
  async function safeSend(text?: string, attachments?: Attachment[]) {
    const raw = (text ?? chat.input ?? "").trim();

    if (!modelLoaded) {
      show("Select a model or activate a worker to start.");
      setShowModelPicker(true);
      return;
    }
    if (!raw && !(attachments && attachments.length)) return;

    // ensure session exists
    let sid = chat.sessionIdRef.current;
    if (!sid) {
      sid = crypto.randomUUID();
      chat.setSessionId(sid);
      try {
        await createChat(sid, "New Chat");
      } catch {}
      localStorage.setItem(LS_KEY, sid);
      setRefreshKey((k) => k + 1);
    }

    try {
      // always stream; backend proxies to worker if one is active
      await chat.send(raw, attachments);
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
    (chat as any).setMessagesForSession?.(sid, () => remaining);
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

  async function handleEjectModel() {
    try {
      await fetch("/api/models/unload", { method: "POST", credentials: "include" });
      setHealth((h) => (h ? { ...h, loaded: false } : { ok: true, loaded: false, config: null }));
    } catch {
      show("Failed to unload model");
    } finally {
      await refreshWorkerReady();
    }
  }

  async function refreshHealth() {
    try {
      const h = await getModelHealth();
      setHealth(h);
      await refreshWorkerReady();
    } catch {}
  }

  return (
    <AgentRunnerView
      // sidebar
      sidebarOpen={sidebarOpen}
      setSidebarOpen={setSidebarOpen}
      openMobileDrawer={openMobileDrawer}
      closeMobileDrawer={closeMobileDrawer}
      // chat + ui state
      chat={chat}
      toast={toast}
      autoFollow={autoFollow}
      refreshKey={refreshKey}
      // model
      modelLoaded={modelLoaded}
      modelName={modelName}
      showModelPicker={showModelPicker}
      setShowModelPicker={setShowModelPicker}
      onEjectModel={handleEjectModel}
      onHealthRefresh={refreshHealth}
      // panels
      showSettings={showSettings}
      setShowSettings={setShowSettings}
      showKnowledge={showKnowledge}
      setShowKnowledge={setShowKnowledge}
      // handlers
      onOpenSession={openSession}
      onNewChat={newChat}
      onCancelSessions={handleCancelSessions}
      onDeleteMessages={handleDeleteMessages}
      safeSend={safeSend}
      showToast={show}
    />
  );
}
