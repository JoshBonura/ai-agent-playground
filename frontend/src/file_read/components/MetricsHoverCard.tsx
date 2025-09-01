// frontend/src/file_read/components/MetricsHoverCard.tsx
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Info, Copy, Check, X } from "lucide-react";
import type { RunJson } from "../shared/lib/runjson";
import {
  getNormalizedBudget,
  getRagTelemetry,
  getWebTelemetry,
  getTimingMetrics,
  getPackTelemetry,
} from "../shared/lib/runjson";

type Props = {
  data: unknown;
  title?: string;
  align?: "left" | "right";
  maxWidthPx?: number;
  compact?: boolean;
};

export default function MetricsHoverCard({
  data,
  title = "Run details",
  align = "right",
  maxWidthPx = 460,
  compact = true,
}: Props) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const btnRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const [panelStyle, setPanelStyle] = useState<{
    top: number;
    left: number;
    width: number;
  } | null>(null);

  const json = useMemo(() => {
    try {
      const r = (data ?? null) as RunJson | null;
      if (!r || typeof r !== "object") return JSON.stringify(data, null, 2);

      const nb = getNormalizedBudget(r);
      const rag = getRagTelemetry(r) as any | null;
      const web = getWebTelemetry(r) as any | null;
      const pack = getPackTelemetry(r) as any | null;
      const timing = getTimingMetrics(r) as any | null;

      const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);

      const modelCtx = nb ? num(nb.modelCtx) : null;
      const clampMargin = nb ? num(nb.clampMargin) : null;
      const inputTokensEst = nb ? num(nb.inputTokensEst) : null;
      const outBudgetChosen = nb ? num(nb.outBudgetChosen) : null;
      const outActual = num(r?.stats?.predictedTokensCount as any);
      const outShown = outActual || (outBudgetChosen ?? 0);

      const webRouteSec = web?.elapsedSec;
      const webFetchSec = web?.fetchElapsedSec;
      const webInjectSec = web?.injectElapsedSec;
      const webPre =
        num(web?.breakdown?.totalWebPreTtftSec) ||
        (num(webRouteSec) + num(webFetchSec) + num(webInjectSec));

      const ragDelta = Math.max(
        0,
        num(rag?.ragTokensAdded) ||
          num(rag?.blockTokens) ||
          num(rag?.blockTokensApprox) ||
          num(rag?.sessionOnlyTokensApprox)
      );
      const ragPctOfInput =
        (inputTokensEst && inputTokensEst > 0) ? Math.round((ragDelta / inputTokensEst) * 100) : 0;

      const packPackSec = num(pack?.packSec);
      const packSummarySec = num(pack?.summarySec);
      const packFinalTrimSec = num(pack?.finalTrimSec);
      const packCompressSec = num(pack?.compressSec);

      const preModelSec = num(timing?.preModelSec);
      const modelQueueSec = num(timing?.modelQueueSec);
      const genSec = num(timing?.genSec);
      const ttftSec = num(timing?.ttftSec);

      const breakdown =
        (r as any)?.budget_view?.breakdown ||
        (r as any)?.stats?.budget?.breakdown ||
        null;

      const preAccountedFromBackend = breakdown?.preTtftAccountedSec;
      const accountedFallback =
        webPre +
        num(rag?.routerDecideSec) +
        num(rag?.injectBuildSec ?? rag?.blockBuildSec ?? rag?.sessionOnlyBuildSec) +
        packPackSec +
        packSummarySec +
        packFinalTrimSec +
        packCompressSec +
        preModelSec +
        modelQueueSec;

      const accounted = Number.isFinite(preAccountedFromBackend)
        ? preAccountedFromBackend
        : accountedFallback;

      const unattributed =
        (breakdown && Number.isFinite(breakdown.unattributedTtftSec))
          ? breakdown.unattributedTtftSec
          : Math.max(0, ttftSec - accounted);

      const promptTok = num(r?.stats?.promptTokensCount as any) || (inputTokensEst ?? 0);
      const decodeTok = num(r?.stats?.predictedTokensCount as any);
      const encodeTps = modelQueueSec > 0 ? promptTok / modelQueueSec : null;
      const decodeTps = genSec > 0 ? decodeTok / genSec : null;

      const totalTok =
        typeof r?.stats?.totalTokensCount === "number"
          ? (r.stats!.totalTokensCount as number)
          : (promptTok + decodeTok);
      const totalSecForOverall =
        typeof r?.stats?.totalTimeSec === "number"
          ? (r.stats!.totalTimeSec as number)
          : num(timing?.totalSec);
      const overallTps =
        totalSecForOverall > 0 ? totalTok / totalSecForOverall : null;

      const usedCtx = (inputTokensEst ?? 0) + outShown + (clampMargin ?? 0);
      const ctxPct = modelCtx && modelCtx > 0 ? Math.max(0, Math.min(100, (usedCtx / modelCtx) * 100)) : null;

      const augmented = {
        ...r,
        _derived: {
          context: {
            modelCtx,
            clampMargin,
            inputTokensEst,
            outBudgetChosen,
            outActual,
            outShown,
            usedCtx,
            ctxPct,
          },
          rag: {
            ragDelta,
            ragPctOfInput,
          },
          web: {
            webPre,
          },
          timing: {
            accountedPreTtftSec: accounted,
            unattributedPreTtftSec: unattributed,
            preModelSec,
            modelQueueSec,
            genSec,
            ttftSec,
          },
          throughput: {
            encodeTokPerSec: encodeTps,
            decodeTokPerSec: decodeTps,
            overallTokPerSec: overallTps,
          },
        },
      };

      return JSON.stringify(augmented, null, 2);
    } catch {
      return String(data ?? "");
    }
  }, [data]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {}
  }

  function close() {
    setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
        btnRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (panelRef.current?.contains(t)) return;
      if (btnRef.current?.contains(t)) return;
      close();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useLayoutEffect(() => {
    function place() {
      if (!open || !btnRef.current) return;

      const margin = 8;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const width = Math.min(maxWidthPx, vw - margin * 2);

      const btnBox = btnRef.current.getBoundingClientRect();
      let left =
        align === "right" ? btnBox.right - width : btnBox.left;
      left = Math.max(margin, Math.min(left, vw - margin - width));

      let top = btnBox.bottom + margin;

      let panelH = panelRef.current?.offsetHeight || 0;
      if (!panelH) {
        panelH = 360 + 44;
      }

      if (top + panelH > vh - margin) {
        top = Math.max(margin, btnBox.top - margin - panelH);
      }

      setPanelStyle({ top, left, width });
    }

    place();
    if (!open) return;

    const onReflow = () => place();
    window.addEventListener("resize", onReflow);
    window.addEventListener("scroll", onReflow, true);
    return () => {
      window.removeEventListener("resize", onReflow);
      window.removeEventListener("scroll", onReflow, true);
    };
  }, [open, align, maxWidthPx]);

  return (
    <div className="relative inline-block">
      <button
        ref={btnRef}
        type="button"
        className={`inline-flex items-center justify-center rounded border bg-white text-gray-700 shadow-sm hover:bg-gray-50 transition ${
          compact ? "h-7 w-7" : "h-8 w-8"
        }`}
        title="Show run JSON"
        aria-haspopup="dialog"
        aria-expanded={open ? "true" : "false"}
        onClick={() => setOpen((v) => !v)}
        onMouseEnter={() => setOpen(true)}
      >
        <Info className={compact ? "w-4 h-4" : "w-5 h-5"} />
      </button>

      {open && panelStyle && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label={title}
          className="fixed z-50"
          style={{
            top: panelStyle.top,
            left: panelStyle.left,
            width: panelStyle.width,
          }}
          onMouseLeave={close}
        >
          <div className="rounded-xl border bg-white shadow-xl overflow-hidden">
            <div className="px-3 py-2 border-b flex items-center justify-between bg-gray-50">
              <div className="text-xs font-semibold text-gray-700">{title}</div>
              <div className="flex items-center gap-1">
                <button
                  className="inline-flex items-center justify-center h-7 w-7 rounded border bg-white text-gray-700 hover:bg-gray-50"
                  onClick={copy}
                  title="Copy JSON"
                >
                  {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                </button>
                <button
                  className="inline-flex items-center justify-center h-7 w-7 rounded border bg-white text-gray-700 hover:bg-gray-50"
                  onClick={close}
                  title="Close"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="p-3">
              <pre className="m-0 p-0 text-xs leading-relaxed overflow-auto" style={{ maxHeight: 360 }}>
                <code>{json}</code>
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
