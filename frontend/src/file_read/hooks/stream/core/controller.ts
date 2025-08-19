import { appendMessage } from "../../data/chatApi";
import type { StreamController, StreamCoreOpts } from "./types";
import { createScheduler, type QueueItem } from "./queue";
import { createCanceller } from "./cancel";
import { runStreamOnce } from "./runner";

export function createStreamController(opts: StreamCoreOpts): StreamController {
  let cancelForSid: string | null = null;
  let controllerRef: AbortController | null = null;
  let readerRef: ReadableStreamDefaultReader<Uint8Array> | null = null;

  const scheduler = createScheduler(async (job: QueueItem) => {
    try { opts.setQueuedFor(job.sid, false); } catch {}
    await runStreamOnce(job, {
      opts,
      getCancelForSid: () => cancelForSid,
      clearCancelIf: (sid) => { if (cancelForSid === sid) cancelForSid = null; },
      setController: (c) => { controllerRef = c; },
      setReader: (r) => { readerRef = r; },
    });
  });

  const canceller = createCanceller({
    getVisibleSid: opts.getSessionId,
    setLoadingFor: opts.setLoadingFor,
    setQueuedFor: opts.setQueuedFor,
    getController: () => controllerRef,
    getReader: () => readerRef,
    setCancelForSid: (sid) => { cancelForSid = sid; },
    isActiveSid: scheduler.isActiveSid,
    dropJobsForSid: scheduler.dropJobsForSid,
  });

  async function send(override?: string) {
    const prompt = (override ?? "").trim();
    if (!prompt) return;
    await opts.ensureChatCreated();
    const sid = opts.getSessionId();

    const asstId = crypto.randomUUID();
    opts.setMessagesFor(sid, (prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", text: prompt },
      { id: asstId, role: "assistant", text: "" },
    ]);
    opts.setInput("");

    appendMessage(sid, "user", prompt)
      .then(() => { try { window.dispatchEvent(new CustomEvent("chats:refresh")); } catch {} })
      .catch(() => {});

    try { opts.setQueuedFor(sid, true); } catch {}
    scheduler.enqueue({ sid, prompt, asstId });
  }

  async function stop() { await canceller.stopVisible(); }
  async function cancelBySessionId(id: string) { await canceller.cancelBySessionId(id); }
  function dispose() {
    try { controllerRef?.abort(); } catch {}
    try { readerRef?.cancel(); } catch {}
    controllerRef = null; readerRef = null;
  }

  return { send, stop, cancelBySessionId, dispose };
}
