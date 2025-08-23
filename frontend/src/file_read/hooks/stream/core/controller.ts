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

    // Stable UI ids
    const userCid = crypto.randomUUID();
    const asstCid = crypto.randomUUID();

    // 1) Optimistically add user + assistant placeholder with serverId=null
    opts.setMessagesFor(sid, (prev) => [
      ...prev,
      { id: userCid, serverId: null, role: "user",      text: prompt },
      { id: asstCid, serverId: null, role: "assistant", text: ""     },
    ]);
    opts.setInput("");

    // 2) Persist user message; patch serverId when we get it
    appendMessage(sid, "user", prompt)
      .then((row) => {
        if (row?.id != null) {
          opts.setServerIdFor(sid, userCid, Number(row.id));
          // Sidebar: make sure the chat shows up as soon as it really exists
          try { window.dispatchEvent(new CustomEvent("chats:refresh")); } catch {}
        }
      })
      .catch(() => { /* ignore; UI stays optimistic */ });

    try { opts.setQueuedFor(sid, true); } catch {}
    scheduler.enqueue({ sid, prompt, asstId: asstCid });
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
