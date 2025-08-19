export type Role = "user" | "assistant";

import type { GenMetrics, RunJson } from "../shared/lib/runjson";

export type ChatMsg = {
  id: string;
  role: Role;
  text: string;

  // Single place to store per-message telemetry (only used on assistant msgs)
  meta?: {
    runJson?: RunJson | null;   // full structured RUNJSON (if present)
    flat?: GenMetrics | null;   // flattened quick metrics
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
  id: number;
  sessionId: string;
  role: Role;
  content: string;
  createdAt: string;
};
