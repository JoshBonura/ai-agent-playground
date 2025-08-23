export type Role = "user" | "assistant";

import type { GenMetrics, RunJson } from "../shared/lib/runjson";

export type ChatMsg = {
  /** Stable UI id that never changes. Always a UUID you assign client-side. */
  id: string; // == clientId
  /** Database id if persisted. Null until the backend saves it. */
  serverId: number | null;

  role: Role;
  text: string;

  // Per-message telemetry (assistant only is typical)
  meta?: {
    runJson?: RunJson | null;
    flat?: GenMetrics | null;
  };
};

export type ChatRow = {
  id: number;
  sessionId: string;
  title: string;
  lastMessage: string | null;
  createdAt: string;
  updatedAt: string;
};

export type ChatMessageRow = {
  id: number;              // server id
  sessionId: string;
  role: Role;
  content: string;
  createdAt: string;
};
