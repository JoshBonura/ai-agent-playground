import { appendMessage } from "../../../data/chatApi";
import type { StreamController, StreamCoreOpts } from "./types";
import { createScheduler, type QueueItem } from "./queue";
import { createCanceller } from "./cancel";
import { runStreamOnce } from "./runner";
import type { Attachment } from "../../../types/chat";

export function createStreamController(opts: StreamCoreOpts): StreamController {
  let cancelForSid: string | null = null;
  let controllerRef: AbortController | null = null;
  let readerRef: ReadableStreamDefaultReader<Uint8Array> | null = null;

  const scheduler = createScheduler(async (job: QueueItem) => {
    try {
      opts.setQueuedFor(job.sid, false);
    } catch {}
    await runStreamOnce(job, {
      opts,
      getCancelForSid: () => cancelForSid,
      clearCancelIf: (sid) => {
        if (cancelForSid === sid) cancelForSid = null;
      },
      setController: (c) => {
        controllerRef = c;
      },
      setReader: (r) => {
        readerRef = r;
      },
    });
  });

  const canceller = createCanceller({
    getVisibleSid: opts.getSessionId,
    setLoadingFor: opts.setLoadingFor,
    setQueuedFor: opts.setQueuedFor,
    getController: () => controllerRef,
    getReader: () => readerRef,
    setCancelForSid: (sid) => {
      cancelForSid = sid;
    },
    isActiveSid: scheduler.isActiveSid,
    dropJobsForSid: scheduler.dropJobsForSid,
  });

  async function send(override?: string, attachments?: Attachment[]) {
    const prompt = (override ?? "").trim();
    const atts = (attachments ?? []).filter(Boolean);
    if (!prompt && atts.length === 0) return; // allow attachments-only, but not truly empty

    await opts.ensureChatCreated();
    const sid = opts.getSessionId();

    const userCid = crypto.randomUUID();
    const asstCid = crypto.randomUUID();

    // optimistic bubbles
    opts.setMessagesFor(sid, (prev) => [
      ...prev,
      {
        id: userCid,
        serverId: null,
        role: "user",
        text: prompt,
        attachments: atts.length ? atts : undefined,
      },
      { id: asstCid, serverId: null, role: "assistant", text: "" },
    ]);
    opts.setInput("");

    // persist user
    appendMessage(sid, "user", prompt, atts.length ? atts : undefined)
      .then((row) => {
        if (row?.id != null) {
          opts.setServerIdFor(sid, userCid, Number(row.id));
          try {
            window.dispatchEvent(
              new CustomEvent("chats:refresh", {
                detail: {
                  sessionId: sid,
                  lastMessage: prompt,
                  updatedAt: new Date().toISOString(),
                },
              }),
            );
          } catch {}
        }
      })
      .catch(() => {});

    // enqueue generation with attachments
    try {
      opts.setQueuedFor(sid, true);
    } catch {}
    scheduler.enqueue({
      sid,
      prompt,
      asstId: asstCid,
      attachments: atts.length ? atts : undefined,
    });
  }

  async function stop() {
    await canceller.stopVisible();
  }
  async function cancelBySessionId(id: string) {
    await canceller.cancelBySessionId(id);
  }
  function dispose() {
    try {
      controllerRef?.abort();
    } catch {}
    try {
      readerRef?.cancel();
    } catch {}
    controllerRef = null;
    readerRef = null;
  }

  return { send, stop, cancelBySessionId, dispose };
}
