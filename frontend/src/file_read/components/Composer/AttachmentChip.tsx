import { X, Check } from "lucide-react";
import ProgressBar from "./ProgressBar";
import type { Att } from "../../hooks/useAttachmentUploads";

export default function AttachmentChip({ a, onRemove }: { a: Att; onRemove: (a: Att) => void }) {
  return (
    <div className="min-w-[160px] max-w-[280px] border rounded-lg px-2 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="truncate text-sm" title={a.name}>{a.name}</div>
        <button className="p-1 rounded hover:bg-gray-100" aria-label="Remove file" onClick={() => onRemove(a)}>
          <X size={14} />
        </button>
      </div>
      <ProgressBar pct={a.pct} error={a.status === "error"} />
      <div className="mt-1 text-xs text-gray-500 flex items-center gap-1">
        {a.status === "uploading" && <span>Uploading… {a.pct}%</span>}
        {a.status === "ready" && <><Check size={14} /> Ready</>}
        {a.status === "error" && <span>Error</span>}
      </div>
    </div>
  );
}
