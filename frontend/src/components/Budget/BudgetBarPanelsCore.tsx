// frontend/src/file_read/components/Budget/BudgetBarPanelsCore.tsx
export const num = (v: unknown) =>
  typeof v === "number" && Number.isFinite(v) ? v : 0;

export function fmtSec(v?: number) {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v < 0.01) return "<0.01s";
  return `${v.toFixed(2)}s`;
}

export function fmtTps(v?: number | null) {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v < 1) return v.toFixed(2);
  if (v < 10) return v.toFixed(1);
  return Math.round(v).toString();
}

type PackPanelProps = {
  pack: any;
  packPackSec: number;
  packSummarySec: number;
  packFinalTrimSec: number;
  packCompressSec: number;
  packSummaryTokens: number;
  packSummaryUsedLLM: boolean;
  droppedMsgs: number;
  droppedApproxTok: number;
  sumShrinkFrom: number;
  sumShrinkTo: number;
  sumShrinkDropped: number;
  rolledPeeledMsgs: number;
  rollNewSummaryTokens: number;
};

export function PackPanel({
  pack,
  packPackSec,
  packSummarySec,
  packFinalTrimSec,
  packCompressSec,
  packSummaryTokens,
  packSummaryUsedLLM,
  droppedMsgs,
  droppedApproxTok,
  sumShrinkFrom,
  sumShrinkTo,
  sumShrinkDropped,
  rolledPeeledMsgs,
  rollNewSummaryTokens,
}: PackPanelProps) {
  return (
    <div className="mt-2 text-[11px] text-gray-700">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {"packSec" in pack && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            pack {fmtSec(packPackSec)}
          </span>
        )}
        {"summarySec" in pack && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            summary {fmtSec(packSummarySec)}{" "}
            {packSummaryUsedLLM ? "(llm)" : "(fast)"}
          </span>
        )}
        {"finalTrimSec" in pack && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            trim {fmtSec(packFinalTrimSec)}
          </span>
        )}
        {"compressSec" in pack && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            compress {fmtSec(packCompressSec)}
          </span>
        )}
        {"summaryTokensApprox" in pack && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            sumTokens≈<b>{packSummaryTokens}</b>
          </span>
        )}
        {"packedChars" in pack && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            packed chars=<b>{(pack as any).packedChars}</b>
          </span>
        )}
        {"messages" in pack && (
          <span className="px-1.5 py-0.5 rounded bg-gray-100 border">
            msgs=<b>{(pack as any).messages}</b>
          </span>
        )}

        {(droppedMsgs > 0 || droppedApproxTok > 0) && (
          <span className="px-1.5 py-0.5 rounded bg-red-50 border border-red-200 text-red-700">
            dropped msgs=<b>{droppedMsgs}</b>
            {droppedApproxTok ? (
              <>
                {" "}
                / ≈<b>{droppedApproxTok}</b> tok
              </>
            ) : null}
          </span>
        )}

        {sumShrinkDropped > 0 && (
          <span className="px-1.5 py-0.5 rounded bg-amber-50 border border-amber-200 text-amber-800">
            summary shrink {sumShrinkFrom}→{sumShrinkTo} chars (−
            <b>{sumShrinkDropped}</b>)
          </span>
        )}

        {rolledPeeledMsgs > 0 && (
          <span className="px-1.5 py-0.5 rounded bg-blue-50 border border-blue-200 text-blue-800">
            rolled: <b>{rolledPeeledMsgs}</b> msgs → +sum≈
            <b>{rollNewSummaryTokens}</b> tok
          </span>
        )}
      </div>
    </div>
  );
}
