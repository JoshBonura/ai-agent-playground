// frontend/src/file_read/hooks/useStream.ts
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMsg } from "../types/chat";
import type { RunJson, GenMetrics } from "../shared/lib/runjson";
import { createStreamController } from "./stream/core/controller";

type UseStreamDeps = {
  // not read directly; keeps memo deps stable
  messages: ChatMsg[];

  // message state per session
  setMessagesForSession: (
    sid: string,
    updater: (prev: ChatMsg[]) => ChatMsg[]
  ) => void;
  getMessagesForSession: (sid: string) => ChatMsg[];

  // ui
  setInput: (v: string) => void;

  // session plumbing
  sessionId: () => string;
  ensureChatCreated: () => Promise<void>;
  onRetitle: (sessionId: string, latestAssistant: string) => Promise<void>;

  // per-session flags/metrics
  setLoadingForSession: (sid: string, v: boolean) => void;
  setQueuedForSession?: (sid: string, v: boolean) => void;
  setMetricsForSession: (sid: string, json?: RunJson, flat?: GenMetrics) => void;
  setMetricsFallbackForSession: (sid: string, reason: string, partialOut: string) => void;
  resetMetricsForSession: (sid: string) => void;
};

export function useStream({
  setMessagesForSession,
  getMessagesForSession,
  setInput,
  sessionId,
  ensureChatCreated,
  onRetitle,
  setLoadingForSession,
  setQueuedForSession,
  setMetricsForSession,
  setMetricsFallbackForSession,
  resetMetricsForSession,
}: UseStreamDeps) {
  const [loading, setLoading] = useState(false);
  const controllerRef = useRef<ReturnType<typeof createStreamController> | null>(null);

  // Build the controller once; it manages its own queue + aborts.
  const controller = useMemo(() => {
    return createStreamController({
      // message access
      getMessagesFor: (sid) => getMessagesForSession(sid),
      setMessagesFor: (sid, updater) => setMessagesForSession(sid, updater),

      // ui hooks
      setInput: () => setInput(""),
      setLoadingFor: (sid, v) => {
        if (sid === sessionId()) setLoading(v);
        setLoadingForSession(sid, v);
      },
      setQueuedFor: setQueuedForSession ?? (() => {}),

      // metrics
      setMetricsFor: (sid, json, flat) => setMetricsForSession(sid, json, flat),
      setMetricsFallbackFor: (sid, reason, out) =>
        setMetricsFallbackForSession(sid, reason, out),

      // NEW: patch server id onto a bubble identified by clientId
      setServerIdFor: (sid, clientId, serverId) => {
        setMessagesForSession(sid, (prev) =>
          prev.map((m) => (m.id === clientId ? { ...m, serverId } : m))
        );
      },

      // session plumbing
      getSessionId: sessionId,
      ensureChatCreated,
      onRetitle,
      resetMetricsFor: (sid) => resetMetricsForSession(sid),
    });
    // Intentionally stable: controller owns its own lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    controllerRef.current = controller;
    return () => controllerRef.current?.dispose();
  }, [controller]);

  async function send(override?: string) {
    const text = (override ?? "").trim();
    if (!text) return;
    await controller.send(text);
  }

  async function stop() {
    await controller.stop();
  }

  async function cancelBySessionId(sid: string) {
    await controller.cancelBySessionId(sid);
  }

  return { loading, send, stop, cancelBySessionId };
}
