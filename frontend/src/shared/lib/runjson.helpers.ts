// frontend/src/file_read/components/shared/lib/runjson.helpers.ts
import {
  MET_START,
  MET_END,
  type RunJson,
  type GenMetrics,
  type BudgetViewJson,
  type TurnBudgetJson,
  type NormalizedBudget,
  type RagTelemetry,
  type WebTelemetry,
  type PackTelemetry,
  type BudgetBreakdown,
} from "./runjson.types";

export function extractRunJsonFromBuffer(buf: string): {
  clean: string;
  json?: RunJson;
  flat?: GenMetrics;
} {
  const re = /(?:\s*)\[\[RUNJSON\]\]\s*([\s\S]*?)\s*\[\[\/RUNJSON\]\](?:\s*)/g;
  let match: RegExpExecArray | null = null;
  let last: RegExpExecArray | null = null;
  while ((match = re.exec(buf)) !== null) last = match;
  if (!last) return { clean: buf };
  const payload = last[1] ?? "";
  let parsed: RunJson | undefined;
  try {
    parsed = JSON.parse(payload) as RunJson;
  } catch {}
  const start = last.index as number;
  const end = start + last[0].length;
  const clean = buf.slice(0, start) + buf.slice(end);
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

export function stripRunJson(raw: string): {
  text: string;
  json?: RunJson;
  flat?: GenMetrics;
} {
  const { clean, json, flat } = extractRunJsonFromBuffer(raw);
  return { text: clean, json, flat };
}

export { MET_START as MET_START_TAG, MET_END as MET_END_TAG };

export function getNormalizedBudget(
  r?: RunJson | null,
): NormalizedBudget | null {
  if (!r) return null;
  const bv = r.budget_view as BudgetViewJson | null | undefined;
  if (bv && bv.modelCtx != null) {
    return {
      modelCtx: bv.modelCtx as number,
      clampMargin: (bv.clampMargin as number) ?? 0,
      inputTokensEst: (bv.inputTokensEst as number) ?? 0,
      outBudgetChosen: (bv.outBudgetChosen as number) ?? 0,
      outBudgetMaxAllowed: (bv.outBudgetMaxAllowed as number) ?? 0,
      overByTokens: (bv.overByTokens as number) ?? 0,
    };
  }
  const tb = r.stats?.budget as TurnBudgetJson | null | undefined;
  if (tb && tb.n_ctx != null) {
    const nctx = tb.n_ctx ?? 0;
    const margin = tb.clamp_margin ?? 0;
    const inp = tb.input_tokens_est ?? 0;
    const chosen = tb.clamped_out_tokens ?? 0;
    const avail = Math.max(0, nctx - inp - margin);
    return {
      modelCtx: nctx,
      clampMargin: margin,
      inputTokensEst: inp,
      outBudgetChosen: chosen,
      outBudgetMaxAllowed: Math.max(0, avail),
      overByTokens: Math.max(0, (tb.requested_out_tokens ?? chosen) - avail),
    };
  }
  return null;
}

export function getRagTelemetry(r?: RunJson | null): RagTelemetry | null {
  if (!r) return null;
  const bv = r.budget_view as BudgetViewJson | null | undefined;
  if (bv?.rag) return bv.rag || null;
  const tb = r.stats?.budget as TurnBudgetJson | null | undefined;
  if (tb?.rag) return tb.rag || null;
  return null;
}

export function getWebTelemetry(r?: RunJson | null): WebTelemetry | null {
  if (!r) return null;
  const bv = r.budget_view as BudgetViewJson | null | undefined;
  if (bv?.web) return bv.web || null;
  const tb = r.stats?.budget as TurnBudgetJson | null | undefined;
  if (tb?.web) return tb.web || null;
  return null;
}

export function getPackTelemetry(r?: RunJson | null): PackTelemetry | null {
  if (!r) return null;
  const bv = r.budget_view as BudgetViewJson | null | undefined;
  if (bv?.pack) return bv.pack || null;
  const tb = r.stats?.budget as TurnBudgetJson | null | undefined;
  if (tb?.pack) return tb.pack || null;
  return null;
}

export function getBudgetBreakdown(r?: RunJson | null): BudgetBreakdown | null {
  if (!r) return null;
  const bv = r.budget_view as BudgetViewJson | null | undefined;
  if (bv?.breakdown) return bv.breakdown || null;
  const tb = (r.stats?.budget as any) || null;
  if (tb?.breakdown) return (tb.breakdown as BudgetBreakdown) || null;
  return null;
}

export function getTimingMetrics(r?: RunJson | null): {
  ttftSec: number | null;
  totalSec: number | null;
  genSec: number | null;
  queueWaitSec: number | null;
  preModelSec: number | null;
  modelQueueSec: number | null;
  engine?: {
    loadSec?: number | null;
    promptSec?: number | null;
    evalSec?: number | null;
    promptN?: number | null;
    evalN?: number | null;
  } | null;
} | null {
  if (!r?.stats) return null;
  const timings: any = (r.stats as any).timings || null;
  const ttftSec =
    typeof timings?.ttftSec === "number"
      ? timings.ttftSec
      : typeof r.stats.timeToFirstTokenSec === "number"
        ? r.stats.timeToFirstTokenSec
        : null;
  const totalSec =
    typeof timings?.totalSec === "number"
      ? timings.totalSec
      : typeof r.stats.totalTimeSec === "number"
        ? r.stats.totalTimeSec
        : null;
  const genSec = typeof timings?.genSec === "number" ? timings.genSec : null;

  const qvFromBV = (r.budget_view as any)?.queueWaitSec;
  const qvFromStats = (r.stats as any)?.budget?.queueWaitSec;
  const queueWaitSec =
    typeof qvFromBV === "number"
      ? qvFromBV
      : typeof qvFromStats === "number"
        ? qvFromStats
        : typeof timings?.queueWaitSec === "number"
          ? timings.queueWaitSec
          : null;

  const preModelSec =
    typeof timings?.preModelSec === "number" ? timings.preModelSec : null;
  const modelQueueSec =
    typeof timings?.modelQueueSec === "number" ? timings.modelQueueSec : null;
  const engine = timings?.engine ?? null;
  return {
    ttftSec,
    totalSec,
    genSec,
    queueWaitSec,
    preModelSec,
    modelQueueSec,
    engine,
  };
}

export function getThroughput(r?: RunJson | null): {
  encodeTps: number | null;
  decodeTps: number | null;
  overallTps: number | null;
  promptN: number | null;
  evalN: number | null;
} | null {
  if (!r?.stats) return null;
  const promptN =
    typeof r.stats.promptTokensCount === "number"
      ? r.stats.promptTokensCount
      : typeof r.stats.timings?.engine?.promptN === "number"
        ? r.stats.timings!.engine!.promptN!
        : null;
  const evalN =
    typeof r.stats.predictedTokensCount === "number"
      ? r.stats.predictedTokensCount
      : typeof r.stats.timings?.engine?.evalN === "number"
        ? r.stats.timings!.engine!.evalN!
        : null;
  const modelQueueSec =
    typeof r.stats.timings?.modelQueueSec === "number"
      ? r.stats.timings!.modelQueueSec!
      : null;
  const genSec =
    typeof r.stats.timings?.genSec === "number"
      ? r.stats.timings!.genSec!
      : null;
  const totalTokens =
    typeof r.stats.totalTokensCount === "number"
      ? r.stats.totalTokensCount
      : null;
  const totalSec =
    typeof r.stats.totalTimeSec === "number"
      ? r.stats.totalTimeSec
      : typeof r.stats.timings?.totalSec === "number"
        ? r.stats.timings!.totalSec!
        : null;
  const safeDiv = (n: number | null, d: number | null) =>
    n != null && d != null && d > 0 ? n / d : null;
  const encodeTps = safeDiv(promptN, modelQueueSec);
  const decodeTps = safeDiv(evalN, genSec);
  const overallTps = safeDiv(totalTokens, totalSec);
  return { encodeTps, decodeTps, overallTps, promptN, evalN };
}
