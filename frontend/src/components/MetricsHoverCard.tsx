// frontend/src/file_read/components/MetricsHoverCard.tsx
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Info } from "lucide-react";
import MetricsHoverCardPanel from "./MetricsHoverCardPanel";

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
  const btnRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [panelStyle, setPanelStyle] = useState<{
    top: number;
    left: number;
    width: number;
  } | null>(null);

  useLayoutEffect(() => {
    function place() {
      if (!open || !btnRef.current) return;
      const margin = 8;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const width = Math.min(maxWidthPx, vw - margin * 2);
      const btnBox = btnRef.current.getBoundingClientRect();
      let left = align === "right" ? btnBox.right - width : btnBox.left;
      left = Math.max(margin, Math.min(left, vw - margin - width));
      let top = btnBox.bottom + margin;
      let panelH = panelRef.current?.offsetHeight || 0;
      if (!panelH) panelH = 360 + 44;
      if (top + panelH > vh - margin)
        top = Math.max(margin, btnBox.top - margin - panelH);
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

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
        btnRef.current?.focus();
      }
    };
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (panelRef.current?.contains(t)) return;
      if (btnRef.current?.contains(t)) return;
      setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  return (
    <div className="relative inline-block">
      <button
        ref={btnRef}
        type="button"
        className={`inline-flex items-center justify-center rounded border bg-white text-gray-700 shadow-sm hover:bg-gray-50 transition ${compact ? "h-7 w-7" : "h-8 w-8"}`}
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
          onMouseLeave={() => setOpen(false)}
        >
          <MetricsHoverCardPanel data={data} title={title} />
        </div>
      )}
    </div>
  );
}
