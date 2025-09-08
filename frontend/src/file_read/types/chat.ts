//aimodel/file_read/types/chat.ts
export type Role = "user" | "assistant";

import type { GenMetrics, RunJson } from "../shared/lib/runjson";

export type Attachment = {
  name: string;
  source?: string;
  sessionId?: string | null;
};

export type ChatMsg = {
  id: string;                // clientId
  serverId: number | null;
  role: Role;
  text: string;

  // NEW
  attachments?: Attachment[];

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
  id: number;
  sessionId: string;
  role: Role;
  content: string;
  createdAt: string;
  attachments?: Attachment[]; // ✅ this must exist
};
