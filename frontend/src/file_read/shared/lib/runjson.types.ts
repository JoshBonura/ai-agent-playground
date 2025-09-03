// frontend/src/file_read/components/shared/lib/runjson.types.ts
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

export type RagTelemetry = {
  routerDecideSec?: number;
  routerNeeded?: boolean;
  routerQuery?: string;
  embedSec?: number;
  searchChatSec?: number;
  searchGlobalSec?: number;
  hitsChat?: number;
  hitsGlobal?: number;
  dedupeSec?: number;
  blockBuildSec?: number;
  injectBuildSec?: number;
  sessionOnlyBuildSec?: number;
  topKRequested?: number;
  blockChars?: number;
  injected?: boolean;
  mode?: string;
  blockTokens?: number;
  blockTokensApprox?: number;
  packedTokensBefore?: number;
  packedTokensAfter?: number;
  ragTokensAdded?: number;
  sessionOnlyTokensApprox?: number;
  sessionOnly?: boolean;
  routerSkipped?: boolean;
  routerSkippedReason?: string;
};


export type WebBreakdown = {
  routerSec?: number;
  summarizeSec?: number;
  searchSec?: number;
  fetchSec?: number;
  jsFetchSec?: number;
  assembleSec?: number;
  orchestratorSec?: number;
  injectSec?: number;
  totalWebPreTtftSec?: number;
  unattributedWebSec?: number;
  prepSec?: number;
};

export type WebTelemetry = {
  needed?: boolean;
  summarizedQuery?: string;
  fetchElapsedSec?: number;
  blockChars?: number;
  injectElapsedSec?: number;
  ephemeralBlocks?: number;
  summarizer?: Record<string, unknown> | null;
  orchestrator?: Record<string, unknown> | null;
  elapsedSec?: number;
  breakdown?: WebBreakdown | null;
};


export type PackTelemetry = {
  packSec?: number;
  summarySec?: number;
  finalTrimSec?: number;
  compressSec?: number;
  summaryTokensApprox?: number;
  summaryUsedLLM?: boolean;
  packedChars?: number;
  messages?: number;


  packInputTokensApprox?: number;
  packMsgs?: number;

  finalTrimTokensBefore?: number;
  finalTrimTokensAfter?: number;
  finalTrimDroppedMsgs?: number;
  finalTrimDroppedApproxTokens?: number;
  finalTrimSummaryShrunkFromChars?: number;
  finalTrimSummaryShrunkToChars?: number;
  finalTrimSummaryDroppedChars?: number;

  rollStartTokens?: number;
  rollOverageTokens?: number;
  rollPeeledMsgs?: number;
  rollNewSummaryChars?: number;
  rollNewSummaryTokensApprox?: number;
};

export type TurnBudgetJson = {
  n_ctx?: number;
  input_tokens_est?: number | null;
  requested_out_tokens?: number;
  clamped_out_tokens?: number;
  clamp_margin?: number;
  reserved_system_tokens?: number | null;
  available_for_out_tokens?: number | null;
  headroom_tokens?: number | null;
  overage_tokens?: number | null;
  reason?: string;
  rag?: RagTelemetry | null;
  web?: WebTelemetry | null;
  pack?: PackTelemetry | null;
};

export type BudgetView = {
  modelCtx: number;
  clampMargin: number;
  usableCtx: number;
  inputTokensEst: number;
  outBudgetChosen: number;
  outBudgetDefault: number;
  outBudgetRequested: number;
  outBudgetMaxAllowed: number;
  overByTokens: number;
  minOutTokens: number;
  queueWaitSec: number | null;
};

export type BudgetBreakdown = {
  ttftSec?: number;
  preTtftAccountedSec?: number;
  unattributedTtftSec?: number;
};

export type BudgetViewJson = Partial<BudgetView> & {
  rag?: RagTelemetry | null;
  web?: WebTelemetry | null;
  pack?: PackTelemetry | null;
  breakdown?: BudgetBreakdown | null;
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
    budget?: TurnBudgetJson | null;
    timings?: {
      queueWaitSec?: number | null;
      genSec?: number | null;
      ttftSec?: number | null;
      totalSec?: number | null;
      preModelSec?: number | null;
      modelQueueSec?: number | null;
      engine?: {
        loadSec?: number | null;
        promptSec?: number | null;
        evalSec?: number | null;
        promptN?: number | null;
        evalN?: number | null;
      } | null;
    } | null;
  };
  budget_view?: BudgetViewJson | null;
  [k: string]: unknown;
};

export type NormalizedBudget = {
  modelCtx: number;
  clampMargin: number;
  inputTokensEst: number;
  outBudgetChosen: number;
  outBudgetMaxAllowed: number;
  overByTokens: number;
};
