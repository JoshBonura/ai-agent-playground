// frontend/src/file_read/hooks/stream/core/queue.ts
import type { Attachment } from "../../../types/chat";

export type QueueItem = {
  sid: string;
  prompt: string;
  asstId: string;
  attachments?: Attachment[];
};

export type RunJob = (job: QueueItem) => Promise<void>;

type Slot = {
  running: boolean;
  q: QueueItem[];
};

export function createScheduler(runJob: RunJob) {
  const slots = new Map<string, Slot>(); // one slot per sid

  async function pump(sid: string) {
    const slot = slots.get(sid);
    if (!slot || slot.running) return;
    const next = slot.q.shift();
    if (!next) return;

    slot.running = true;
    try {
      await runJob(next);
    } finally {
      slot.running = false;
      if (slot.q.length) {
        void pump(sid);
      } else {
        // optional: clean up empty slots
        slots.delete(sid);
      }
    }
  }

  return {
    enqueue(job: QueueItem) {
      let slot = slots.get(job.sid);
      if (!slot) {
        slot = { running: false, q: [] };
        slots.set(job.sid, slot);
      }
      slot.q.push(job);
      void pump(job.sid);
    },

    isActiveSid: (sid: string) => !!slots.get(sid)?.running,

    dropJobsForSid(sid: string) {
      const slot = slots.get(sid);
      if (slot) {
        slot.q.length = 0; // keep running job; clear the rest
      }
    },

    getActiveSid: () => null, // no longer meaningful globally
  };
}
