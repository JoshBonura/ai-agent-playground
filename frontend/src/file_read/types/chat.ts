export type Role = "user" | "assistant";

export type ChatMsg = {
  id: string;
  role: Role;
  text: string;
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
