// frontend/src/file_read/hooks/stream/core/types.ts
import type { ChatMsg, Attachment } from "../../../types/chat";
import type { GenMetrics, RunJson } from "../../../shared/lib/runjson";

export type MsgAccessor = {
  getMessagesFor: (sessionId: string) => ChatMsg[];
  setMessagesFor: (
    sessionId: string,
    updater: (prev: ChatMsg[]) => ChatMsg[],
  ) => void;
};

export type UiHooks = {
  setInput: (v: string) => void;
  setLoadingFor: (sessionId: string, v: boolean) => void;
  setQueuedFor: (sessionId: string, v: boolean) => void;
  setMetricsFor: (sessionId: string, json?: RunJson, flat?: GenMetrics) => void;
  setMetricsFallbackFor: (
    sessionId: string,
    reason: string,
    partialOut: string,
  ) => void;

  /** patch the server id for a bubble identified by clientId */
  setServerIdFor: (sid: string, clientId: string, serverId: number) => void;
};

export type SessionPlumbing = {
  getSessionId: () => string;
  ensureChatCreated: () => Promise<void>;
  onRetitle: (sessionId: string, latestAssistant: string) => Promise<void>;
  resetMetricsFor: (sessionId: string) => void;
};

export type StreamCoreOpts = MsgAccessor & UiHooks & SessionPlumbing;

export type StreamController = {
  /** text can be empty if attachments are present */
  send: (override?: string, attachments?: Attachment[]) => Promise<void>;
  stop: () => Promise<void>;
  cancelBySessionId: (sid: string) => Promise<void>;
  dispose: () => void;
};
