// frontend/src/file_read/hooks/stream/core/buffer.ts
import type { GenMetrics, RunJson } from "../../../shared/lib/runjson";
import { extractRunJsonFromBuffer } from "../../../shared/lib/runjson";
import { STOP_SENTINEL_AT_END } from "./constants";

export type BufferStep = {
  cleanText: string;
  delta: string;
  metrics?: { json?: RunJson; flat?: GenMetrics };
};

/** Strip SSE noise from a raw text/event-stream body that we read via fetch(). */
function stripSSENoise(raw: string): string {
  let s = raw;

  // 1) Drop pure comment lines like ": proxy-open" or ": hb"
  s = s.replace(/^\s*:[^\n]*\n?/gm, "");

  // 2) Drop non-data SSE fields (defensive — we currently don't send data: frames for tokens)
  s = s.replace(/^(?:event|id|retry):[^\n]*\n?/gm, "");

  // 3) If we ever emit proper "data:" frames, unwrap them back to plain text
  s = s.replace(/^data:\s?/gm, "");

  return s;
}

export function processChunk(prevClean: string, rawBufIn: string): BufferStep {
  let rawBuf = rawBufIn;

  // Remove the visible STOP line if present
  if (STOP_SENTINEL_AT_END.test(rawBuf)) {
    rawBuf = rawBuf.replace(STOP_SENTINEL_AT_END, "");
  }

  // NEW: strip SSE comments/fields so they never reach the chat bubble
  rawBuf = stripSSENoise(rawBuf);

  // Keep your existing RUNJSON extraction & diffing
  const { clean, json, flat } = extractRunJsonFromBuffer(rawBuf);
  const delta = clean.slice(prevClean.length);

  return {
    cleanText: clean,
    delta,
    metrics: json || flat ? { json, flat } : undefined,
  };
}
