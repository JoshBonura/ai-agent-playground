import { useMemo, useRef, useState } from "react";
import { Info, Copy, Check, X } from "lucide-react";

type Props = {
  data: unknown;                 // anything JSON-serializable
  title?: string;                // optional header
  align?: "left" | "right";      // popover alignment
  maxWidthPx?: number;           // width of the panel
  compact?: boolean;             // shrink button & paddings
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
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  }

  // accessibility: close on ESC
  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      setOpen(false);
      btnRef.current?.focus();
    }
  }

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
        onMouseLeave={() => setOpen(false)}
      >
        <Info className={compact ? "w-4 h-4" : "w-5 h-5"} />
      </button>

      {/* Panel */}
      <div
        role="dialog"
        aria-label={title}
        onKeyDown={onKeyDown}
        className={`absolute z-50 mt-2 ${align === "right" ? "right-0" : "left-0"}`}
        style={{ width: Math.min(maxWidthPx, window.innerWidth - 40) }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        <div
          className={`rounded-xl border bg-white shadow-xl overflow-hidden transition
          ${open ? "opacity-100 translate-y-0" : "pointer-events-none opacity-0 -translate-y-1"}`}
        >
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
                onClick={() => setOpen(false)}
                title="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="p-3">
            <pre
              className="m-0 p-0 text-xs leading-relaxed overflow-auto"
              style={{ maxHeight: 360 }}
            >
              <code>{json}</code>
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}
