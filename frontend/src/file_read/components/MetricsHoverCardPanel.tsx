// frontend/src/file_read/components/MetricsHoverCardPanel.tsx
import { useMemo, useState } from "react";
import { Copy, Check, X } from "lucide-react";
import type { RunJson } from "../shared/lib/runjson";
import {
  getNormalizedBudget,
  getRagTelemetry,
  getWebTelemetry,
  getTimingMetrics,
  getPackTelemetry,
} from "../shared/lib/runjson";

type PanelProps = {
  data: unknown;
  title: string;
};

const asNum = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const num0 = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);

export default function MetricsHoverCardPanel({ data, title }: PanelProps) {
  const [copied, setCopied] = useState(false);

  const json = useMemo(() => {
    try {
      const r = (data ?? null) as RunJson | null;
      if (!r || typeof r !== "object") return JSON.stringify(data, null, 2);

      const nb = getNormalizedBudget(r);
      const rag = getRagTelemetry(r) as any | null;
      const web = getWebTelemetry(r) as any | null;
      const pack = getPackTelemetry(r) as any | null;
      const timing = getTimingMetrics(r) as any | null;

      const modelCtx = nb ? num0(nb.modelCtx) : null;
      const clampMargin = nb ? num0(nb.clampMargin) : null;
      const inputTokensEst = nb ? num0(nb.inputTokensEst) : null;
      const outBudgetChosen = nb ? num0(nb.outBudgetChosen) : null;
      const outActual = num0((r as any)?.stats?.predictedTokensCount);
      const outShown = outActual || (outBudgetChosen ?? 0);

      const webRouteSec = web?.elapsedSec;
      const webFetchSec = web?.fetchElapsedSec;
      const webInjectSec = web?.injectElapsedSec;
      const webPre =
        num0(web?.breakdown?.totalWebPreTtftSec) ||
        (num0(webRouteSec) + num0(webFetchSec) + num0(webInjectSec));

      const ragDelta = Math.max(
        0,
        num0((rag as any)?.ragTokensAdded) ||
          num0((rag as any)?.blockTokens) ||
          num0((rag as any)?.blockTokensApprox) ||
          num0((rag as any)?.sessionOnlyTokensApprox)
      );
      const ragPctOfInput =
        inputTokensEst && inputTokensEst > 0 ? Math.round((ragDelta / inputTokensEst) * 100) : 0;

      const packPackSec = num0(pack?.packSec);
      const packSummarySec = num0(pack?.summarySec);
      const packFinalTrimSec = num0(pack?.finalTrimSec);
      const packCompressSec = num0(pack?.compressSec);

      const preModelSec = num0(timing?.preModelSec);
      const modelQueueSec = num0(timing?.modelQueueSec);
      const genSec = num0(timing?.genSec);
      const ttftSec = num0(timing?.ttftSec);

      const breakdown = (r as any)?.budget_view?.breakdown || (r as any)?.stats?.budget?.breakdown || null;

      const preAccountedFromBackend = breakdown?.preTtftAccountedSec;
      const accountedFallback =
        webPre +
        num0((rag as any)?.routerDecideSec) +
        num0((rag as any)?.injectBuildSec ?? (rag as any)?.blockBuildSec ?? (rag as any)?.sessionOnlyBuildSec) +
        packPackSec +
        packSummarySec +
        packFinalTrimSec +
        packCompressSec +
        preModelSec +
        modelQueueSec;

      const accounted = Number.isFinite(preAccountedFromBackend) ? preAccountedFromBackend : accountedFallback;

      const unattributed =
        breakdown && Number.isFinite(breakdown.unattributedTtftSec)
          ? breakdown.unattributedTtftSec
          : Math.max(0, ttftSec - accounted);

      const promptTok = num0((r as any)?.stats?.promptTokensCount) || (inputTokensEst ?? 0);
      const decodeTok = num0((r as any)?.stats?.predictedTokensCount);
      const encodeTps = modelQueueSec > 0 ? promptTok / modelQueueSec : null;
      const decodeTps = genSec > 0 ? decodeTok / genSec : null;

      const totalTok =
        typeof (r as any)?.stats?.totalTokensCount === "number"
          ? ((r as any).stats.totalTokensCount as number)
          : promptTok + decodeTok;
      const totalSecForOverall =
        typeof (r as any)?.stats?.totalTimeSec === "number"
          ? ((r as any).stats.totalTimeSec as number)
          : num0(timing?.totalSec);
      const overallTps = totalSecForOverall > 0 ? totalTok / totalSecForOverall : null;

      const usedCtx = (inputTokensEst ?? 0) + outShown + (clampMargin ?? 0);
      const ctxPct = modelCtx && modelCtx > 0 ? Math.max(0, Math.min(100, (usedCtx / modelCtx) * 100)) : null;

      const augmented = {
        ...r,
        _derived: {
          context: { modelCtx, clampMargin, inputTokensEst, outBudgetChosen, outActual, outShown, usedCtx, ctxPct },
          rag: { ragDelta, ragPctOfInput },
          web: { webPre },
          timing: {
            accountedPreTtftSec: accounted,
            unattributedPreTtftSec: unattributed,
            preModelSec,
            modelQueueSec,
            genSec,
            ttftSec,
          },
          throughput: { encodeTokPerSec: encodeTps, decodeTokPerSec: decodeTps, overallTokPerSec: overallTps },
        },
      };

      return JSON.stringify(augmented, null, 2);
    } catch {
      return String(data ?? "");
    }
  }, [data]);

  return (
    <div className="rounded-xl border bg-white shadow-xl overflow-hidden">
      <div className="px-3 py-2 border-b flex items-center justify-between bg-gray-50">
        <div className="text-xs font-semibold text-gray-700">{title}</div>
        <div className="flex items-center gap-1">
          <button
            className="inline-flex items-center justify-center h-7 w-7 rounded border bg-white text-gray-700 hover:bg-gray-50"
            onClick={() => {
              navigator.clipboard.writeText(json);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            }}
            title="Copy JSON"
          >
            {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
          </button>
          <button
            className="inline-flex items-center justify-center h-7 w-7 rounded border bg-white text-gray-700 hover:bg-gray-50"
            onClick={() => {}}
            title="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* JSON only; badges removed */}
      <div className="p-3">
        <pre className="m-0 p-0 text-xs leading-relaxed overflow-auto" style={{ maxHeight: 360 }}>
          <code>{json}</code>
        </pre>
      </div>
    </div>
  );
}
