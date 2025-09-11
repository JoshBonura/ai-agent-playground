import type { RunJson, GenMetrics } from "../../../shared/lib/runjson";
import type { ChatMsg } from "../../../types/chat";

type Opts = {
  setMetricsFor: (sid: string, json?: RunJson, flat?: GenMetrics) => void;
  setMessagesFor: (sid: string, fn: (prev: ChatMsg[]) => ChatMsg[]) => void;
  setMetricsFallbackFor: (sid: string, reason: string, text: string) => void;
};

export function pinLiveMetricsToSession(
  opts: Opts,
  sid: string,
  json?: RunJson,
  flat?: GenMetrics,
) {
  opts.setMetricsFor(sid, json, flat);
}

export function pinLiveMetricsToBubble(
  opts: Opts,
  sid: string,
  asstId: string,
  json?: RunJson,
  flat?: GenMetrics,
) {
  opts.setMessagesFor(sid, (prev) =>
    prev.map((m) =>
      m.id === asstId
        ? {
            ...m,
            meta: {
              ...(m.meta ?? {}),
              runJson: json ?? m.meta?.runJson,
              flat: flat ?? m.meta?.flat,
            },
          }
        : m,
    ),
  );
}

/** Also returns the synthesized RunJson so caller can persist if needed. */
export function pinFallbackToSessionAndBubble(
  opts: Opts,
  sid: string,
  asstId: string,
  reason: string,
  finalText: string,
): RunJson {
  const json: RunJson = {
    stats: {
      stopReason: reason,
      tokensPerSecond: null,
      timeToFirstTokenSec: null,
      totalTimeSec: null,
      promptTokensCount: null,
      predictedTokensCount: finalText ? finalText.length : 0,
      totalTokensCount: null,
    },
  };
  const flat: GenMetrics = {
    stop_reason: reason,
    tok_per_sec: null,
    ttft_ms: null,
    output_tokens: null,
    input_tokens_est: null,
    total_tokens_est: null,
  };

  opts.setMetricsFallbackFor(sid, reason, finalText);
  opts.setMessagesFor(sid, (prev) =>
    prev.map((m) =>
      m.id === asstId
        ? { ...m, meta: { ...(m.meta ?? {}), runJson: json, flat } }
        : m,
    ),
  );
  return json;
}
