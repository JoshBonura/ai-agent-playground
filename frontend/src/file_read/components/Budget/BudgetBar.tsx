// frontend/src/file_read/components/chat/Budget/BudgetBar.tsx
import type { RunJson } from "../../shared/lib/runjson";
import { getNormalizedBudget, getRagTelemetry, getWebTelemetry, getTimingMetrics, getPackTelemetry } from "../../shared/lib/runjson";

function pct(n: number, d: number) {
  if (!Number.isFinite(n) || !Number.isFinite(d) || d <= 0) return 0;
  return Math.max(0, Math.min(100, (n / d) * 100));
}
function fmtSec(v?: number) {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v < 0.01) return "<0.01s";
  return `${v.toFixed(2)}s`;
}
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);

export default function BudgetBar({ runJson }: { runJson?: RunJson | null }) {
  const nb = getNormalizedBudget(runJson ?? undefined);
  if (!nb) return null;

  const rag = getRagTelemetry(runJson ?? undefined) as any | null;
  const web = getWebTelemetry(runJson ?? undefined) as any | null;
  const pack = getPackTelemetry(runJson ?? undefined) as any | null;
  const timing = getTimingMetrics(runJson ?? undefined) as any | null;

  const modelCtx = num(nb.modelCtx);
  const clampMargin = num(nb.clampMargin);
  const inputTokensEst = num(nb.inputTokensEst);
  const outBudgetChosen = num(nb.outBudgetChosen);

  const used = inputTokensEst + outBudgetChosen + clampMargin;
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
  const ragBlockBuildTime = rag?.injectBuildSec ?? rag?.blockBuildSec ?? rag?.sessionOnlyBuildSec;

  const webWasInjected = !!web?.injected;
  const webNeeded = web?.needed;
  const webRouteSec = web?.elapsedSec;
  const webFetchSec = web?.fetchElapsedSec;
  const webInjectSec = web?.injectElapsedSec;
  const webBlockChars = web?.blockChars;
  const webEphemeralBlocks = web?.ephemeralBlocks;

  const packPackSec = num(pack?.packSec);
  const packSummarySec = num(pack?.summarySec);
  const packFinalTrimSec = num(pack?.finalTrimSec);
  const packCompressSec = num(pack?.compressSec);
  const packSummaryTokens = num(pack?.summaryTokensApprox);
  const packSummaryUsedLLM = !!pack?.summaryUsedLLM;

  const engine = timing?.engine || null;
  const engineLoadSec = num(engine?.loadSec);
  const enginePromptSec = num(engine?.promptSec);
  const engineEvalSec = num(engine?.evalSec);
  const enginePromptN = engine?.promptN;
  const engineEvalN = engine?.evalN;

  const accounted =
    num(webRouteSec) +
    num(webFetchSec) +
    num(webInjectSec) +
    num(rag?.routerDecideSec) +
    num(ragBlockBuildTime) +
    packPackSec +
    packSummarySec +
    packFinalTrimSec +
    packCompressSec +
    engineLoadSec +
    enginePromptSec;
  const unattributed = Math.max(0, num(timing?.ttftSec ?? null) - accounted);

  return (
    <div className="px-3 py-2 border-t bg-white/90 backdrop-blur sticky bottom-0 z-40">
      <div className="flex items-center gap-3 text-[11px] text-gray-700">
        <div className="flex-1 h-1.5 rounded bg-gray-200 overflow-hidden" title={`Context ${fullPct.toFixed(1)}%`}>
          <div className="h-1.5 bg-black" style={{ width: `${fullPct}%` }} />
        </div>
        <div className="whitespace-nowrap">
          Input: <span className="font-medium">{inputTokensEst}</span>
        </div>
        <div className="whitespace-nowrap">
          Out: <span className="font-medium">{outBudgetChosen}</span>
        </div>
        <div className="whitespace-nowrap">
          Ctx: <span className="font-medium">{modelCtx}</span>
        </div>
        <div className="whitespace-nowrap text-gray-500">{`Context is ${fullPct.toFixed(1)}% full`}</div>
      </div>

      {pack && (
        <div className="mt-2 text-[11px] text-gray-700">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            {"packSec" in pack && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">pack {fmtSec(packPackSec)}</span>}
            {"summarySec" in pack && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
                summary {fmtSec(packSummarySec)} {packSummaryUsedLLM ? "(llm)" : "(fast)"}
              </span>
            )}
            {"finalTrimSec" in pack && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">trim {fmtSec(packFinalTrimSec)}</span>
            )}
            {"compressSec" in pack && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">compress {fmtSec(packCompressSec)}</span>
            )}
            {"summaryTokensApprox" in pack && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">sumTokens≈<b>{packSummaryTokens}</b></span>
            )}
            {"packedChars" in pack && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">packed chars=<b>{pack.packedChars}</b></span>
            )}
            {"messages" in pack && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">msgs=<b>{pack.messages}</b></span>
            )}
          </div>
        </div>
      )}

      {rag && (
        <div className="mt-2 text-[11px] text-gray-700">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
              RAG: <b>{ragWasInjected ? "injected" : "skipped"}</b> {rag.mode ? `(${rag.mode})` : rag.sessionOnly ? "(session-only)" : ""}
            </span>
            {"routerNeeded" in rag && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">router: <b>{rag.routerNeeded ? "yes" : "no"}</b></span>
            )}
            {"routerDecideSec" in rag && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">route {fmtSec(rag.routerDecideSec)}</span>}
            {"embedSec" in rag && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">embed {fmtSec(rag.embedSec)}</span>}
            {("searchChatSec" in rag || "searchGlobalSec" in rag) && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">search {fmtSec(rag.searchChatSec)} / {fmtSec(rag.searchGlobalSec)}</span>
            )}
            {"dedupeSec" in rag && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">dedupe {fmtSec(rag.dedupeSec)}</span>}
            {ragBlockBuildTime !== undefined && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">block {fmtSec(ragBlockBuildTime)}</span>}
            {rag.topKRequested != null && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">k=<b>{rag.topKRequested}</b></span>}
            {rag.hitsChat != null && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">hits chat=<b>{rag.hitsChat}</b></span>}
            {rag.hitsGlobal != null && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">global=<b>{rag.hitsGlobal}</b></span>}
            {(rag.ragTokensAdded != null || rag.blockTokens != null || rag.blockTokensApprox != null || rag.sessionOnlyTokensApprox != null) && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
                +RAG tokens=<b>{ragDelta}</b>
                {inputTokensEst ? ` (${ragPctOfInput}% of input)` : ""}
              </span>
            )}
            {(rag.blockChars != null || rag.sessionOnlyChars != null) && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">block chars=<b>{rag.blockChars ?? rag.sessionOnlyChars}</b></span>
            )}
          </div>
          {rag.routerQuery && (
            <div className="mt-1 text-[10px] text-gray-500 truncate" title={rag.routerQuery}>
              query: {rag.routerQuery}
            </div>
          )}
        </div>
      )}

      {web && (
        <div className="mt-2 text-[11px] text-gray-700">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
              WEB: <b>{webWasInjected ? "injected" : "skipped"}</b>
              {webNeeded !== undefined ? <> (router: <b>{webNeeded ? "need" : "no"}</b>)</> : null}
            </span>
            {"elapsedSec" in web && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">route {fmtSec(webRouteSec)}</span>}
            {"fetchElapsedSec" in web && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">fetch {fmtSec(webFetchSec)}</span>}
            {"injectElapsedSec" in web && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">inject {fmtSec(webInjectSec)}</span>}
            {"blockChars" in web && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">block chars=<b>{webBlockChars}</b></span>}
            {"ephemeralBlocks" in web && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">eph blocks=<b>{webEphemeralBlocks}</b></span>}
          </div>
          {web.summarizedQuery && (
            <div className="mt-1 text-[10px] text-gray-500 truncate" title={web.summarizedQuery}>
              query: {web.summarizedQuery}
            </div>
          )}
        </div>
      )}

      {timing && (
        <div className="mt-2 text-[11px] text-gray-700">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="px-1.5 py-0.5 rounded bg-gray-100 border">ttft {fmtSec(timing.ttftSec ?? undefined)}</span>
            {"queueWaitSec" in timing && timing.queueWaitSec != null && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">queue {fmtSec(timing.queueWaitSec)}</span>
            )}
            {"genSec" in timing && timing.genSec != null && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">gen {fmtSec(timing.genSec)}</span>
            )}
            {"totalSec" in timing && timing.totalSec != null && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 border">total {fmtSec(timing.totalSec)}</span>
            )}
            {!!enginePromptSec && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">prefill {fmtSec(enginePromptSec)}</span>}
            {!!engineEvalSec && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">eval {fmtSec(engineEvalSec)}</span>}
            {!!engineLoadSec && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">load {fmtSec(engineLoadSec)}</span>}
            {enginePromptN != null && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">promptN={enginePromptN}</span>}
            {engineEvalN != null && <span className="px-1.5 py-0.5 rounded bg-gray-100 border">evalN={engineEvalN}</span>}
            <span className="px-1.5 py-0.5 rounded bg-gray-100 border">unattributed {fmtSec(unattributed)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
