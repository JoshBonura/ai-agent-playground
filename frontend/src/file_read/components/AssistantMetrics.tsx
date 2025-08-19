// frontend/src/file_read/components/chat/AssistantMetrics.tsx
import { Info } from "lucide-react";
import MetricsHoverCard from "./MetricsHoverCard";
import type { RunJson, GenMetrics } from "../shared/lib/runjson";

export default function AssistantMetrics({
  status,
  runJson,
  flat,
  align = "right",
}: { status: string; runJson?: RunJson | null; flat?: GenMetrics | null; align?: "left" | "right" }) {
  return (
    <div className="mt-2 flex justify-start">
      <div className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-white border shadow-sm text-[11px] text-gray-600">
        <Info className="w-3.5 h-3.5 opacity-70" />
        <span className="truncate max-w-[70vw] sm:max-w-none">{status || "Run details"}</span>
        <MetricsHoverCard
          data={
            runJson ??
            (flat
              ? {
                  stats: {
                    stopReason: flat.stop_reason ?? null,
                    tokensPerSecond: flat.tok_per_sec ?? null,
                    timeToFirstTokenSec: flat.ttft_ms != null ? Math.max(0, flat.ttft_ms) / 1000 : null,
                    totalTimeSec: null,
                    promptTokensCount: flat.input_tokens_est ?? null,
                    predictedTokensCount: flat.output_tokens ?? null,
                    totalTokensCount: flat.total_tokens_est ?? null,
                  },
                }
              : null)
          }
          title="Run JSON"
          align={align}
          compact
        />
      </div>
    </div>
  );
}
