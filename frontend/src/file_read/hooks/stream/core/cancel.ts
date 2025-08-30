import { postCancel } from "./network";
import { STOP_FLUSH_TIMEOUT_MS } from "./constants";

type Deps = {
  getVisibleSid: () => string;
  setLoadingFor: (sid: string, v: boolean) => void;
  setQueuedFor: (sid: string, v: boolean) => void;
  getController: () => AbortController | null;
  getReader: () => ReadableStreamDefaultReader<Uint8Array> | null;
  setCancelForSid: (sid: string | null) => void;
  isActiveSid: (sid: string) => boolean;
  dropJobsForSid: (sid: string) => void;
};

export function createCanceller(d: Deps) {
  async function cancelBySessionId(id: string) {
    // Mark as canceled so read loop can react, but DO NOT abort fetch yet.
    d.setCancelForSid(id);

    // Tell the backend to stop gracefully (flush metrics + close).
    postCancel(id).catch(() => {});

    if (d.isActiveSid(id)) {
      // Drop any queued jobs for this session, but keep loading true —
      // runStreamOnce will turn loading off in its finally after the stream ends.
      d.dropJobsForSid(id);
      d.setQueuedFor(id, false);

      // Safety net: if server doesn’t flush within timeout, hard-abort.
      window.setTimeout(() => {
        if (d.isActiveSid(id)) {
          try { d.getReader()?.cancel(); } catch {}
          try { d.getController()?.abort(); } catch {}
        }
      }, STOP_FLUSH_TIMEOUT_MS + 500);
    } else {
      // Not active: just clear queued jobs and cancel flag.
      d.dropJobsForSid(id);
      d.setQueuedFor(id, false);
      d.setCancelForSid(null);
    }
  }

  async function stopVisible() {
    const id = d.getVisibleSid();
    await cancelBySessionId(id);
  }

  return { cancelBySessionId, stopVisible };
}
