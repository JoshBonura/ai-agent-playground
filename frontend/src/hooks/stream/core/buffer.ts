// frontend/src/file_read/hooks/stream/core/buffer.ts
import type { GenMetrics, RunJson } from "../../../shared/lib/runjson";
import { extractRunJsonFromBuffer } from "../../../shared/lib/runjson";
import { STOP_SENTINEL_AT_END } from "./constants";

export type BufferStep = {
  cleanText: string;
  delta: string;
  metrics?: { json?: RunJson; flat?: GenMetrics };
};

export function processChunk(prevClean: string, rawBufIn: string): BufferStep {
  let rawBuf = rawBufIn;
  if (STOP_SENTINEL_AT_END.test(rawBuf)) {
    rawBuf = rawBuf.replace(STOP_SENTINEL_AT_END, "");
  }
  const { clean, json, flat } = extractRunJsonFromBuffer(rawBuf);
  const delta = clean.slice(prevClean.length);
  return {
    cleanText: clean,
    delta,
    metrics: json || flat ? { json, flat } : undefined,
  };
}
