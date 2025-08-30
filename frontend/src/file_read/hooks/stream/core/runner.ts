// frontend/src/file_read/hooks/stream/core/runner.ts
import { postStream } from "./network";
import { ensureAssistantPlaceholder, snapshotPendingAssistant } from "./updater";
import type { ChatMsg } from "../../../types/chat";
import type { RunJson, GenMetrics } from "../../../shared/lib/runjson";
import { readStreamLoop } from "./runner_stream";
import {
  pinLiveMetricsToSession,
  pinLiveMetricsToBubble,
  pinFallbackToSessionAndBubble,
} from "./runner_metrics";
import { persistAssistantTurn } from "./runner_persist";
import type { QueueItem } from "./queue";
import { listChatsPage } from "../../../data/chatApi";


export type RunnerDeps = {
  opts: {
    ensureChatCreated: () => Promise<void>;
    getSessionId: () => string;
    getMessagesFor: (sid: string) => ChatMsg[];
    setMessagesFor: (sid: string, fn: (prev: ChatMsg[]) => ChatMsg[]) => void;
    setInput: (v: string) => void;
    setLoadingFor: (sid: string, v: boolean) => void;
    setQueuedFor: (sid: string, v: boolean) => void;
    resetMetricsFor: (sid: string) => void;
    setMetricsFor: (sid: string, json?: RunJson, flat?: GenMetrics) => void;
    setMetricsFallbackFor: (sid: string, reason: string, text: string) => void;
    onRetitle: (sid: string, finalText: string) => Promise<void>;
    setServerIdFor: (sid: string, clientId: string, serverId: number) => void;
  };
  getCancelForSid: () => string | null;
  clearCancelIf: (sid: string) => void;
  setController: (c: AbortController | null) => void;
  setReader: (r: ReadableStreamDefaultReader<Uint8Array> | null) => void;
};

export async function runStreamOnce(job: QueueItem, d: RunnerDeps) {
  const { sid, prompt, asstId, attachments } = job;
  const { opts } = d;
  const wasCanceled = () => d.getCancelForSid() === sid;

  opts.resetMetricsFor(sid);
  opts.setLoadingFor(sid, true);

  ensureAssistantPlaceholder(
    { getMessagesFor: opts.getMessagesFor, setMessagesFor: opts.setMessagesFor },
    sid,
    asstId
  );

  const MAX_HISTORY = 10;
  const history = opts
    .getMessagesFor(sid)
    .slice(-MAX_HISTORY)
    .map((m) => ({
      role: m.role,
      content: m.text || "",
      attachments: m.attachments && m.attachments.length ? m.attachments : undefined,
    }))
    .filter(
      (m) =>
        (m.content && m.content.trim().length > 0) ||
        (m.attachments && m.attachments.length > 0)
    );

  const userTurn = {
    role: "user" as const,
    content: prompt,
    attachments: attachments && attachments.length ? attachments : undefined,
  };

  const controller = new AbortController();
  d.setController(controller);
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

  try {
    reader = await postStream(
      { sessionId: sid, messages: [...history, userTurn] },
      controller.signal
    );
    d.setReader(reader);

    const { finalText, gotMetrics, lastRunJson } = await readStreamLoop(reader, {
      wasCanceled,
      onDelta: (delta) => {
        opts.setMessagesFor(sid, (prev) => {
          const idx = prev.findIndex((m) => m.id === asstId);
          if (idx === -1) return prev;
          const next = [...prev];
          next[idx] = { ...next[idx], text: (next[idx].text || "") + delta };
          return next;
        });
      },
      onMetrics: (json, flat) => {
        pinLiveMetricsToSession(opts, sid, json, flat);
        pinLiveMetricsToBubble(opts, sid, asstId, json, flat);
      },
      onCancelTimeout: (cleanSoFar) => {
        opts.setMetricsFallbackFor(sid, "user_cancel_timeout", cleanSoFar);
      },
    });

    let persistJson: RunJson | null = gotMetrics ? lastRunJson : null;

    if (!gotMetrics) {
      const reason = wasCanceled() ? "user_cancel" : "end_of_stream_no_metrics";
      const fallback = pinFallbackToSessionAndBubble(opts, sid, asstId, reason, finalText);
      if (!wasCanceled()) persistJson = fallback;
    }

    if (!wasCanceled() && finalText.trim()) {
      const newServerId = await persistAssistantTurn(sid, finalText, persistJson);
      if (newServerId != null) {
        opts.setServerIdFor(sid, asstId, newServerId);
      }

      try { await opts.onRetitle(sid, finalText); } catch {}
      try {
        window.dispatchEvent(
          new CustomEvent("chats:refresh", {
            detail: {
              sessionId: sid,
              lastMessage: finalText,
              updatedAt: new Date().toISOString(),
            },
          })
        );
      } catch {}

      const pokeForTitle = (delayMs: number) => {
        window.setTimeout(async () => {
          try {
            const ceil = new Date().toISOString();
            const page = await listChatsPage(0, 30, ceil);
            const row = page.content.find((r: any) => r.sessionId === sid);
            if (row?.title) {
              window.dispatchEvent(
                new CustomEvent("chats:refresh", {
                  detail: {
                    sessionId: sid,
                    title: row.title,
                    updatedAt: row.updatedAt,
                  },
                })
              );
            }
          } catch {}
        }, delayMs);
      };
      pokeForTitle(1000);
      pokeForTitle(3000);
    }
  } catch (e: any) {
    const localAbort =
      e?.name === "AbortError" && (wasCanceled() || controller.signal.aborted);
    const reason = localAbort ? "client_abort_after_stop" : e?.name || "client_error";

    const last = snapshotPendingAssistant(opts.getMessagesFor(sid));
    opts.setMetricsFallbackFor(sid, reason, last);
    pinFallbackToSessionAndBubble(opts, sid, asstId, reason, last);

    opts.setMessagesFor(sid, (prev) => {
      const end = prev[prev.length - 1];
      if (end?.role === "assistant" && !end.text.trim()) {
        return prev.map((m, i) =>
          i === prev.length - 1 ? { ...m, text: "[stream error]" } : m
        );
      }
      return prev;
    });
  } finally {
    if (d.getCancelForSid() === sid) d.clearCancelIf(sid);
    opts.setLoadingFor(sid, false);
    d.setController(null);
    d.setReader(null);
  }
}
