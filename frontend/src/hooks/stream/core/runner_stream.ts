import { STOP_FLUSH_TIMEOUT_MS } from "./constants";
import type { RunJson, GenMetrics } from "../../../shared/lib/runjson";
import { processChunk } from "./buffer";

type LoopDeps = {
  wasCanceled: () => boolean;
  onDelta: (delta: string, cleanSoFar: string) => void;
  onMetrics: (json?: RunJson, flat?: GenMetrics) => void;
  onCancelTimeout: (cleanSoFar: string) => void;
};

export async function readStreamLoop(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  d: LoopDeps,
): Promise<{
  finalText: string;
  gotMetrics: boolean;
  lastRunJson: RunJson | null;
}> {
  const decoder = new TextDecoder();
  let rawBuf = "";
  let cleanSoFar = "";
  let gotMetrics = false;
  let lastRunJson: RunJson | null = null;
  let stopTimeout: number | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    if (value) {
      rawBuf += decoder.decode(value, { stream: true });
      const step = processChunk(cleanSoFar, rawBuf);

      if (step.metrics) {
        gotMetrics = true;
        if (step.metrics.json) lastRunJson = step.metrics.json;
        d.onMetrics(step.metrics.json, step.metrics.flat);
      }
      if (step.delta) {
        cleanSoFar = step.cleanText;
        d.onDelta(step.delta, cleanSoFar);
      }
    }

    // If user canceled, schedule a final flush check, but DO NOT break early
    if (d.wasCanceled() && stopTimeout === null) {
      stopTimeout = window.setTimeout(() => {
        if (!gotMetrics) d.onCancelTimeout(cleanSoFar);
      }, STOP_FLUSH_TIMEOUT_MS) as unknown as number;
    }
  }

  if (stopTimeout !== null) {
    // If we scheduled a timeout but finished before it fired, synthesize now.
    if (!gotMetrics && d.wasCanceled()) {
      d.onCancelTimeout(cleanSoFar);
    }
    window.clearTimeout(stopTimeout);
  }

  return { finalText: cleanSoFar, gotMetrics, lastRunJson };
}
