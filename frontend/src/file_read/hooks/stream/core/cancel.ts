import { postCancel } from "./network";

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
    d.setCancelForSid(id);

    if (d.isActiveSid(id)) {
      try { d.getController()?.abort(); } catch {}
      try { d.getReader()?.cancel(); } catch {}
      d.setLoadingFor(id, false);
    } else {
      d.dropJobsForSid(id);
      d.setQueuedFor(id, false);
      d.setCancelForSid(null);
    }

    // fire-and-forget server stop
    postCancel(id).catch(() => {});
  }

  async function stopVisible() {
    const id = d.getVisibleSid();
    await cancelBySessionId(id);
  }

  return { cancelBySessionId, stopVisible };
}
