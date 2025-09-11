// frontend/src/file_read/hooks/stream/core/queue.ts
import type { Attachment } from "../../../types/chat";

export type QueueItem = {
  sid: string;
  prompt: string; // may be empty when attachments-only
  asstId: string; // client id of the assistant bubble to stream into
  attachments?: Attachment[]; // optional attachments for this turn
};

export type RunJob = (job: QueueItem) => Promise<void>;

export function createScheduler(runJob: RunJob) {
  const q: QueueItem[] = [];
  let active: { sid: string } | null = null;

  async function startNext() {
    if (active || q.length === 0) return;
    const job = q.shift()!;
    active = { sid: job.sid };
    try {
      await runJob(job);
    } finally {
      active = null;
      if (q.length) void startNext();
    }
  }

  return {
    enqueue(job: QueueItem) {
      q.push(job);
      void startNext();
    },
    isActiveSid: (sid: string) => active?.sid === sid,
    dropJobsForSid(sid: string) {
      for (let i = q.length - 1; i >= 0; i--) {
        if (q[i].sid === sid) q.splice(i, 1);
      }
    },
    getActiveSid: () => active?.sid ?? null,
  };
}
