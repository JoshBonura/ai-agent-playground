// src/file_read/utils/runjson.ts
export const MET_START = "[[RUNJSON]]";
export const MET_END = "[[/RUNJSON]]";

export type GenMetrics = {
  ttft_ms?: number | null;
  tok_per_sec?: number | null;
  output_tokens?: number | null;
  input_tokens_est?: number | null;
  total_tokens_est?: number | null;
  stop_reason?: string | null;
};

export type RunJson = {
  stats?: {
    stopReason?: string | null;
    tokensPerSecond?: number | null;
    timeToFirstTokenSec?: number | null;
    totalTimeSec?: number | null;
    promptTokensCount?: number | null;
    predictedTokensCount?: number | null;
    totalTokensCount?: number | null;
  };
  [k: string]: unknown;
};

// Robustly extract the last [[RUNJSON]] ... [[/RUNJSON]] block, tolerating
// surrounding spaces/newlines and any placement within the text.
export function extractRunJsonFromBuffer(
  buf: string
): { clean: string; json?: RunJson; flat?: GenMetrics } {
  // Use a global, dotall regex that captures the JSON payload and allows
  // optional whitespace around the delimiters.
  const re =
    /(?:\s*)\[\[RUNJSON\]\]\s*([\s\S]*?)\s*\[\[\/RUNJSON\]\](?:\s*)/g;

  let match: RegExpExecArray | null = null;
  let lastMatch: RegExpExecArray | null = null;

  while ((match = re.exec(buf)) !== null) {
    lastMatch = match; // keep the last one if multiple blocks appear
  }

  if (!lastMatch) {
    // nothing found -> leave as-is
    return { clean: buf };
  }

  const fullSpan = lastMatch[0];
  const payload = lastMatch[1] ?? "";

  let parsed: RunJson | undefined;
  try {
    parsed = JSON.parse(payload) as RunJson;
  } catch {
    // if JSON parse fails, still strip the span from the clean text
  }

  // Remove exactly the matched span (not all occurrences).
  const startIdx = (lastMatch.index as number);
  const endIdx = startIdx + fullSpan.length;
  const clean = buf.slice(0, startIdx) + buf.slice(endIdx);

  // Flatten if we have stats
  let flat: GenMetrics | undefined;
  const s = parsed?.stats;
  if (s) {
    flat = {
      ttft_ms:
        s.timeToFirstTokenSec != null
          ? Math.max(0, s.timeToFirstTokenSec) * 1000
          : null,
      tok_per_sec: s.tokensPerSecond ?? null,
      output_tokens: s.predictedTokensCount ?? null,
      input_tokens_est: s.promptTokensCount ?? null,
      total_tokens_est: s.totalTokensCount ?? null,
      stop_reason: s.stopReason ?? null,
    };
  }

  return { clean, json: parsed, flat };
}

// For one-shot responses (e.g., title bot)
export function stripRunJson(raw: string): {
  text: string;
  json?: RunJson;
  flat?: GenMetrics;
} {
  const { clean, json, flat } = extractRunJsonFromBuffer(raw);
  return { text: clean, json, flat };
}

// (kept exports for any external references)
export { MET_START as MET_START_TAG, MET_END as MET_END_TAG };
