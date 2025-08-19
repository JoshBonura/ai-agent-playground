import { useState } from "react";
import type { GenMetrics, RunJson } from "../shared/lib/runjson";

export function useRunMetrics() {
  const [runMetrics, setRunMetrics] = useState<GenMetrics | null>(null);
  const [runJson, setRunJson] = useState<RunJson | null>(null);

  function resetMetrics() {
    setRunMetrics(null);
    setRunJson(null);
  }

  function setFromParsed(json?: RunJson, flat?: GenMetrics) {
    if (json) setRunJson(json);
    if (flat) setRunMetrics(flat);
  }

  function synthesizeStop(reason: string, partialOut: string) {
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
    return { json, flat };
  }

  function setFallback(reason: string, partialOut: string) {
    const { json, flat } = synthesizeStop(reason, partialOut);
    setRunJson(prev => prev ?? json);
    setRunMetrics(prev => prev ?? flat);
  }

  return {
    runMetrics,
    runJson,
    resetMetrics,
    setFromParsed,
    setFallback,
  };
}

export type { GenMetrics, RunJson } from "../shared/lib/runjson";
