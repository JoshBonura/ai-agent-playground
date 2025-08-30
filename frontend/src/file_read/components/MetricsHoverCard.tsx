// frontend/src/file_read/components/MetricsHoverCard.tsx
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Info, Copy, Check, X } from "lucide-react";

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
      return JSON.stringify(data, null, 2);
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

  // Close on ESC
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

  // Close on outside click
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

  // Compute clamped viewport position when opening, and on resize/scroll
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

      // Provisional top below the button; flip above if it would overflow
      let top = btnBox.bottom + margin;

      // We may not know the panel height yet; try to use current, else a max
      let panelH = panelRef.current?.offsetHeight || 0;
      if (!panelH) {
        panelH = 360 + 44; // body max (360) + header (~44) best-effort
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
