// frontend/src/file_read/components/Budget/BudgetBar.tsx

import { useState } from "react";
import {
  type RunJson,
  getNormalizedBudget,
  getRagTelemetry,
  getWebTelemetry,
  getTimingMetrics,
  getPackTelemetry,
  getThroughput,
} from "../../shared/lib/runjson";
import {
  RagPanel,
  WebPanel,
  TimingPanel,
} from "./BudgetBarPanelsExtras";
import {
  num,
  PackPanel,
} from "./BudgetBarPanelsCore";

import { ChevronDown, ChevronUp } from "lucide-react";

function pct(n: number, d: number) {
  if (!Number.isFinite(n) || !Number.isFinite(d) || d <= 0) return 0;
  return Math.max(0, Math.min(100, (n / d) * 100));
}

export default function BudgetBar({ runJson }: { runJson?: RunJson | null }) {
  const nb = getNormalizedBudget(runJson ?? undefined);
  if (!nb) return null;

  const [open, setOpen] = useState(false);

  const rag = getRagTelemetry(runJson ?? undefined) as any | null;
  const web = getWebTelemetry(runJson ?? undefined) as any | null;
  const pack = getPackTelemetry(runJson ?? undefined) as any | null;
  const timing = getTimingMetrics(runJson ?? undefined) as any | null;
  const tps = getThroughput(runJson ?? undefined);

  const breakdown =
    (runJson as any)?.budget_view?.breakdown ??
    (runJson as any)?.stats?.budget?.breakdown ??
    null;

  const modelCtx = num(nb.modelCtx);
  const clampMargin = num(nb.clampMargin);
  const inputTokensEst = num(nb.inputTokensEst);
  const outBudgetChosen = num(nb.outBudgetChosen);
  const outActual = num(runJson?.stats?.predictedTokensCount);
  const outShown = outActual || outBudgetChosen;

  const used = inputTokensEst + outShown + clampMargin;
  const fullPct = pct(used, modelCtx);

  const ragDelta = Math.max(
    0,
    num(rag?.ragTokensAdded) ||
      num(rag?.blockTokens) ||
      num(rag?.blockTokensApprox) ||
      num(rag?.sessionOnlyTokensApprox)
  );
  const ragWasInjected = !!(rag?.injected || rag?.sessionOnly || ragDelta > 0);
  const ragPctOfInput = inputTokensEst > 0 ? Math.round((ragDelta / inputTokensEst) * 100) : 0;
  const ragBlockBuildTime =
    rag?.injectBuildSec ?? rag?.blockBuildSec ?? rag?.sessionOnlyBuildSec;

  const webRouteSec = web?.elapsedSec;
  const webFetchSec = web?.fetchElapsedSec;
  const webInjectSec = web?.injectElapsedSec;
  const webPre =
    num((web as any)?.breakdown?.totalWebPreTtftSec) ||
    (num(webRouteSec) + num(webFetchSec) + num(webInjectSec));

  const packPackSec = num(pack?.packSec);
  const packSummarySec = num(pack?.summarySec);
  const packFinalTrimSec = num(pack?.finalTrimSec);
  const packCompressSec = num(pack?.compressSec);
  const packSummaryTokens = num(pack?.summaryTokensApprox);
  const packSummaryUsedLLM = !!pack?.summaryUsedLLM;

  const droppedMsgs = num((pack as any)?.finalTrimDroppedMsgs);
  const droppedApproxTok = num((pack as any)?.finalTrimDroppedApproxTokens);
  const sumShrinkFrom = num((pack as any)?.finalTrimSummaryShrunkFromChars);
  const sumShrinkTo = num((pack as any)?.finalTrimSummaryShrunkToChars);
  const sumShrinkDropped = num((pack as any)?.finalTrimSummaryDroppedChars);
  const rolledPeeledMsgs = num((pack as any)?.rollPeeledMsgs);
  const rollNewSummaryTokens = num((pack as any)?.rollNewSummaryTokensApprox);

  const engine = timing?.engine || null;
  const engineLoadSec = num(engine?.loadSec);
  const enginePromptSec = num(engine?.promptSec);
  const engineEvalSec = num(engine?.evalSec);
  const enginePromptN = engine?.promptN;
  const engineEvalN = engine?.evalN;

  const preModelSec = num(timing?.preModelSec);
  const modelQueueSec = num(timing?.modelQueueSec);

  const preAccountedFromBackend = num(breakdown?.preTtftAccountedSec);
  const accountedFallback =
    webPre +
    num(rag?.routerDecideSec) +
    num(ragBlockBuildTime) +
    packPackSec +
    packSummarySec +
    packFinalTrimSec +
    packCompressSec +
    preModelSec +
    modelQueueSec;
  const accounted = preAccountedFromBackend || accountedFallback;

  const unattributed =
    (breakdown && Number.isFinite(breakdown.unattributedTtftSec))
      ? num(breakdown.unattributedTtftSec)
      : Math.max(0, num(timing?.ttftSec) - accounted);

  return (
    <div className="px-3 py-2 border-t bg-white/90 backdrop-blur sticky bottom-0 z-40">
      <div className="flex items-center gap-2 text-[11px] text-gray-700">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open ? "true" : "false"}
          className="shrink-0 inline-flex items-center gap-1 px-2 h-6 rounded border bg-white hover:bg-gray-50"
          title={open ? "Hide details" : "Show details"}
        >
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
          <span className="hidden sm:inline">Details</span>
        </button>

        <div
          className="flex-1 h-1.5 rounded bg-gray-200 overflow-hidden"
          title={`Context ${fullPct.toFixed(1)}%`}
        >
          <div className="h-1.5 bg-black" style={{ width: `${fullPct}%` }} />
        </div>

        <div className="whitespace-nowrap hidden xs:block">
          In: <span className="font-medium">{inputTokensEst}</span>
        </div>
        <div className="whitespace-nowrap hidden xs:block">
          Out: <span className="font-medium">{outShown}</span>
        </div>
        <div className="whitespace-nowrap hidden sm:block">
          Ctx: <span className="font-medium">{modelCtx}</span>
        </div>
        <div className="whitespace-nowrap text-gray-500 hidden md:block">
          {`Context is ${fullPct.toFixed(1)}% full`}
        </div>
      </div>

      {open && (
        <div className="mt-2 max-h-40 sm:max-h-48 md:max-h-56 overflow-y-auto pr-1 pb-1 -mr-1">
          {pack && (
            <PackPanel
              pack={pack}
              packPackSec={packPackSec}
              packSummarySec={packSummarySec}
              packFinalTrimSec={packFinalTrimSec}
              packCompressSec={packCompressSec}
              packSummaryTokens={packSummaryTokens}
              packSummaryUsedLLM={packSummaryUsedLLM}
              droppedMsgs={droppedMsgs}
              droppedApproxTok={droppedApproxTok}
              sumShrinkFrom={sumShrinkFrom}
              sumShrinkTo={sumShrinkTo}
              sumShrinkDropped={sumShrinkDropped}
              rolledPeeledMsgs={rolledPeeledMsgs}
              rollNewSummaryTokens={rollNewSummaryTokens}
            />
          )}

          {rag && (
            <RagPanel
              rag={rag}
              ragWasInjected={ragWasInjected}
              ragBlockBuildTime={ragBlockBuildTime}
              ragDelta={ragDelta}
              ragPctOfInput={ragPctOfInput}
              inputTokensEst={inputTokensEst}
            />
          )}

          {web && <WebPanel web={web} />}

          {timing && (
            <TimingPanel
              timing={timing}
              enginePromptSec={enginePromptSec}
              engineEvalSec={engineEvalSec}
              engineLoadSec={engineLoadSec}
              enginePromptN={enginePromptN}
              engineEvalN={engineEvalN}
              preModelSec={preModelSec}
              modelQueueSec={modelQueueSec}
              unattributed={unattributed}
              encodeTps={tps?.encodeTps ?? null}
              decodeTps={tps?.decodeTps ?? null}
              overallTps={tps?.overallTps ?? null}
            />
          )}
        </div>
      )}
    </div>
  );
}
