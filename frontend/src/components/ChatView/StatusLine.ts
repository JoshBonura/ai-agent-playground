// frontend/src/file_read/components/chat/StatusLine.ts
import type { RunJson, GenMetrics } from "../../shared/lib/runjson";

const oneDec = (n?: number | null) =>
  typeof n === "number" && Number.isFinite(n) ? n.toFixed(1) : undefined;

export function buildStatus(json?: RunJson | null, flat?: GenMetrics | null) {
  const st = json?.stats;
  if (st) {
    const parts: string[] = [];
    if (st.predictedTokensCount != null)
      parts.push(`${st.predictedTokensCount} tok`);
    if (st.tokensPerSecond != null)
      parts.push(`${oneDec(st.tokensPerSecond) ?? st.tokensPerSecond} tok/s`);
    if (st.timeToFirstTokenSec != null)
      parts.push(`TTFT ${Math.round(st.timeToFirstTokenSec * 1000)} ms`);
    if (st.stopReason) parts.push(`stop: ${st.stopReason}`);
    return parts.join(" • ");
  }
  if (flat) {
    const parts: string[] = [];
    if (flat.output_tokens != null) parts.push(`${flat.output_tokens} tok`);
    if (flat.tok_per_sec != null)
      parts.push(`${oneDec(flat.tok_per_sec) ?? flat.tok_per_sec} tok/s`);
    if (flat.ttft_ms != null) parts.push(`TTFT ${Math.round(flat.ttft_ms)} ms`);
    if (flat.stop_reason) parts.push(`stop: ${flat.stop_reason}`);
    return parts.join(" • ");
  }
  return "";
}
