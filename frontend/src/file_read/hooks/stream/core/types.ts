// frontend/src/file_read/hooks/stream/core/types.ts
import type { ChatMsg } from "../../../types/chat";
import type { GenMetrics, RunJson } from "../../../shared/lib/runjson";

export type MsgAccessor = {
  getMessagesFor: (sessionId: string) => ChatMsg[];
  setMessagesFor: (sessionId: string, updater: (prev: ChatMsg[]) => ChatMsg[]) => void;
};

export type UiHooks = {
  setInput: (v: string) => void;
  setLoadingFor: (sessionId: string, v: boolean) => void;
  setQueuedFor: (sessionId: string, v: boolean) => void; // NEW
  setMetricsFor: (sessionId: string, json?: RunJson, flat?: GenMetrics) => void;
  setMetricsFallbackFor: (sessionId: string, reason: string, partialOut: string) => void;
};

export type SessionPlumbing = {
  getSessionId: () => string;
  ensureChatCreated: () => Promise<void>;
  onRetitle: (sessionId: string, latestAssistant: string) => Promise<void>;
  resetMetricsFor: (sessionId: string) => void;
};

export type StreamCoreOpts = MsgAccessor & UiHooks & SessionPlumbing;

export type StreamController = {
  send: (override?: string) => Promise<void>;
  stop: () => Promise<void>;                        // cancels current visible session
  cancelBySessionId: (sid: string) => Promise<void>; // NEW: cancel a specific session
  dispose: () => void;
};
