// frontend/src/file_read/components/Budget/BudgetBarPanelsExtras.tsx
import { fmtSec, fmtTps } from "./BudgetBarPanelsCore";

type RagPanelProps = {
  rag: any;
  ragWasInjected: boolean;
  ragBlockBuildTime?: number;
  ragDelta: number;
  ragPctOfInput: number;
  inputTokensEst: number;
};

export function RagPanel({
  rag,
  ragWasInjected,
  ragBlockBuildTime,
  ragDelta,
  ragPctOfInput,
  inputTokensEst,
}: RagPanelProps) {
  const routerNeeded = rag?.routerNeeded;
  const routerDecideSec = rag?.routerDecideSec;
  const embedSec = rag?.embedSec;
  const searchChatSec = rag?.searchChatSec;
  const searchGlobalSec = rag?.searchGlobalSec;
  const dedupeSec = rag?.dedupeSec;
  const topKRequested = rag?.topKRequested;
  const hitsChat = rag?.hitsChat;
  const hitsGlobal = rag?.hitsGlobal;
  const blockChars = rag?.blockChars ?? rag?.sessionOnlyChars;
  const routerQuery = rag?.routerQuery;

  return (
    <div className="mt-2 text-[11px] text-gray-700">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
          RAG: <b>{ragWasInjected ? "injected" : "skipped"}</b>{" "}
          {rag?.mode ? `(${rag.mode})` : rag?.sessionOnly ? "(session-only)" : ""}
        </span>
        {"routerNeeded" in rag && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            router: <b>{routerNeeded ? "yes" : "no"}</b>
          </span>
        )}
        {"routerDecideSec" in rag && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            route {fmtSec(routerDecideSec)}
          </span>
        )}
        {"embedSec" in rag && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            embed {fmtSec(embedSec)}
          </span>
        )}
        {("searchChatSec" in rag || "searchGlobalSec" in rag) && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            search {fmtSec(searchChatSec)} / {fmtSec(searchGlobalSec)}
          </span>
        )}
        {"dedupeSec" in rag && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            dedupe {fmtSec(dedupeSec)}
          </span>
        )}
        {ragBlockBuildTime !== undefined && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            block {fmtSec(ragBlockBuildTime)}
          </span>
        )}
        {topKRequested != null && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">k=<b>{topKRequested}</b></span>
        )}
        {hitsChat != null && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">hits chat=<b>{hitsChat}</b></span>
        )}
        {hitsGlobal != null && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">global=<b>{hitsGlobal}</b></span>
        )}

        {(rag.ragTokensAdded != null ||
          rag.blockTokens != null ||
          rag.blockTokensApprox != null ||
          rag.sessionOnlyTokensApprox != null) && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            +RAG tokens=<b>{ragDelta}</b>
            {inputTokensEst ? ` (${ragPctOfInput}% of input)` : ""}
          </span>
        )}

        {blockChars != null && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            block chars=<b>{blockChars}</b>
          </span>
        )}
      </div>

      {routerQuery && (
        <div
          className="mt-1 text-[10px] text-gray-500 truncate"
          title={routerQuery}
        >
          query: {routerQuery}
        </div>
      )}
    </div>
  );
}

type WebPanelProps = {
  web: any;
};

export function WebPanel({ web }: WebPanelProps) {
  const webWasInjected = !!web?.injected;
  const webNeeded = web?.needed;
  const webRouteSec = web?.elapsedSec;
  const webFetchSec = web?.fetchElapsedSec;
  const webInjectSec = web?.injectElapsedSec;
  const webBlockChars = web?.blockChars;
  const webEphemeralBlocks = web?.ephemeralBlocks;
  const summarizedQuery = web?.summarizedQuery;

  return (
    <div className="mt-2 text-[11px] text-gray-700">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
          WEB: <b>{webWasInjected ? "injected" : "skipped"}</b>
          {webNeeded !== undefined ? (
            <> (router: <b>{webNeeded ? "need" : "no"}</b>)</>
          ) : null}
        </span>
        {"elapsedSec" in web && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            route {fmtSec(webRouteSec)}
          </span>
        )}
        {"fetchElapsedSec" in web && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            fetch {fmtSec(webFetchSec)}
          </span>
        )}
        {"injectElapsedSec" in web && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            inject {fmtSec(webInjectSec)}
          </span>
        )}
        {"blockChars" in web && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            block chars=<b>{webBlockChars}</b>
          </span>
        )}
        {"ephemeralBlocks" in web && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            eph blocks=<b>{webEphemeralBlocks}</b>
          </span>
        )}
      </div>

      {summarizedQuery && (
        <div
          className="mt-1 text-[10px] text-gray-500 truncate"
          title={summarizedQuery}
        >
          query: {summarizedQuery}
        </div>
      )}
    </div>
  );
}

type TimingPanelProps = {
  timing: any;
  enginePromptSec?: number;
  engineEvalSec?: number;
  engineLoadSec?: number;
  enginePromptN?: number | null;
  engineEvalN?: number | null;
  preModelSec?: number;
  modelQueueSec?: number;
  unattributed?: number;
  encodeTps?: number | null;
  decodeTps?: number | null;
  overallTps?: number | null;
};

export function TimingPanel({
  timing,
  enginePromptSec,
  engineEvalSec,
  engineLoadSec,
  enginePromptN,
  engineEvalN,
  preModelSec,
  modelQueueSec,
  unattributed,
  encodeTps,
  decodeTps,
  overallTps,
}: TimingPanelProps) {
  return (
    <div className="mt-2 text-[11px] text-gray-700">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
          ttft {fmtSec(timing.ttftSec ?? undefined)}
        </span>
        {"queueWaitSec" in timing && timing.queueWaitSec != null && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            queue {fmtSec(timing.queueWaitSec)}
          </span>
        )}
        {"genSec" in timing && timing.genSec != null && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            gen {fmtSec(timing.genSec)}
          </span>
        )}
        {"totalSec" in timing && timing.totalSec != null && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            total {fmtSec(timing.totalSec)}
          </span>
        )}
        {!!enginePromptSec && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            prefill {fmtSec(enginePromptSec)}
          </span>
        )}
        {!!engineEvalSec && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            eval {fmtSec(engineEvalSec)}
          </span>
        )}
        {!!engineLoadSec && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            load {fmtSec(engineLoadSec)}
          </span>
        )}
        {enginePromptN != null && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            promptN={enginePromptN}
          </span>
        )}
        {engineEvalN != null && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            evalN={engineEvalN}
          </span>
        )}
        {!!preModelSec && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            pre-model {fmtSec(preModelSec)}
          </span>
        )}
        {!!modelQueueSec && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            model-queue {fmtSec(modelQueueSec)}
          </span>
        )}
        <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
          unattributed {fmtSec(unattributed)}
        </span>
        {encodeTps != null && (
          <span className="px-1.5 py-0.5 rounded bg-green-50 border border-green-200 text-green-800">
            encode <b>{fmtTps(encodeTps)}</b> tok/s
          </span>
        )}
        {decodeTps != null && (
          <span className="px-1.5 py-0.5 rounded bg-indigo-50 border border-indigo-200 text-indigo-800">
            decode <b>{fmtTps(decodeTps)}</b> tok/s
          </span>
        )}
        {overallTps != null && (
          <span className="px-1.5 py-0.5 rounded bg-gray-50 border">
            overall <b>{fmtTps(overallTps)}</b> tok/s
          </span>
        )}
      </div>
    </div>
  );
}
