import { useState } from "react";
import type { GenMetrics, RunJson } from "../shared/lib/runjson";

type BySession<T> = Record<string, T>;
type Pair = { runJson: RunJson | null; flat: GenMetrics | null };

export function useMetrics() {
  const [metricsBy, setMetricsBy] = useState<BySession<Pair>>({});

  function resetMetricsFor(sid: string) {
    setMetricsBy((prev) => ({ ...prev, [sid]: { runJson: null, flat: null } }));
  }

  function setMetricsFor(sid: string, json?: RunJson, flat?: GenMetrics) {
    setMetricsBy((prev) => {
      const cur = prev[sid] ?? { runJson: null, flat: null };
      return { ...prev, [sid]: { runJson: json ?? cur.runJson, flat: flat ?? cur.flat } };
    });
  }

  function setMetricsFallbackFor(sid: string, reason: string, partialOut: string) {
    const json: RunJson = {
      stats: {
        stopReason: reason,
        tokensPerSecond: null,
        timeToFirstTokenSec: null,
        totalTimeSec: null,
        promptTokensCount: null,
        predictedTokensCount: partialOut ? partialOut.length : 0,
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
    setMetricsFor(sid, json, flat);
  }

  return { metricsBy, resetMetricsFor, setMetricsFor, setMetricsFallbackFor };
}
