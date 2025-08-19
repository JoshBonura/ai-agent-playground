import { useMemo } from "react";
import type { ChatMsg } from "../types/chat";
import { useSession } from "./useSession";
import { useStream } from "./useStream";
import { useChatState } from "./useChatState";
import { useRunState } from "./useRunState";
import { useMetrics } from "./useMetrics";

export type { GenMetrics, RunJson } from "../shared/lib/runjson";

export function useChatStream() {
  // state slices
  const chat = useChatState();
  const run = useRunState();
  const met = useMetrics();

  // session plumbing
  const { sessionIdRef, ensureChatCreated, loadHistory, setSessionId, resetSession } = useSession({
    setMessagesForSession: (sid: string, msgs: ChatMsg[]) => chat.setMsgs(sid, msgs),
    getMessagesForSession: (sid: string) => chat.getMsgs(sid),
    isStreaming: (sid: string) => !!run.loadingBy[sid],
  });

  // stream controller
  const { send, stop, cancelBySessionId } = useStream({
    messages: chat.getMsgs(sessionIdRef.current), // keeps deps stable
    setMessagesForSession: (sid, updater) => chat.setMsgs(sid, updater),
    getMessagesForSession: chat.getMsgs,
    setInput: chat.setInput,
    sessionId: () => sessionIdRef.current,
    ensureChatCreated,
    onRetitle: async () => {},
    setLoadingForSession: run.setLoadingFor,
    setQueuedForSession: run.setQueuedFor,
    setMetricsForSession: met.setMetricsFor,
    setMetricsFallbackForSession: met.setMetricsFallbackFor,
    resetMetricsForSession: met.resetMetricsFor,
  });

  async function cancelSessions(ids: string[]) {
    await Promise.all(ids.map(cancelBySessionId));
  }

  // derived (active session)
  const activeId = sessionIdRef.current;
  const messages = useMemo(() => chat.getMsgs(activeId), [chat.bySession, activeId]);
  const loading = !!run.loadingBy[activeId];
  const queued = !!run.queuedBy[activeId];
  const runJson = met.metricsBy[activeId]?.runJson ?? null;
  const runMetrics = met.metricsBy[activeId]?.flat ?? null;

  function reset() {
    chat.setInput("");
    met.resetMetricsFor(activeId);
    resetSession();
  }

  function snapshotPendingAssistant(): string {
    const msgs = chat.getMsgs(activeId);
    const last = msgs[msgs.length - 1];
    return last?.role === "assistant" ? (last.text ?? "") : "";
  }

  return {
    // chat state
    messages,
    input: chat.input,
    setInput: chat.setInput,
    loading,
    queued,

    // actions
    send,
    stop,
    cancelSessions,

    // session ctl
    setSessionId,
    sessionIdRef,
    loadHistory,
    reset,
    snapshotPendingAssistant,

    // metrics (active only)
    runMetrics,
    runJson,
    clearMetrics: () => met.resetMetricsFor(activeId),
  };
}
