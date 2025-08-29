// frontend/src/file_read/components/KnowledgePanel.tsx
import { useState } from "react";
import { uploadRag, searchRag } from "../data/ragApi";

export default function KnowledgePanel({
  sessionId,
  onClose,
  toast,
}: {
  sessionId?: string;
  onClose?: () => void;
  toast?: (msg: string) => void;
}) {
  const [files, setFiles] = useState<FileList | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<{ text: string; source?: string; score: number }[]>([]);
  const [searching, setSearching] = useState(false);

async function doUpload() {
  console.log("[KnowledgePanel] doUpload clicked", files);

  if (!files || !files.length) {
    console.warn("[KnowledgePanel] no files selected");
    return;
  }

  setBusy(true);
  try {
    let total = 0;
    for (const f of Array.from(files)) {
      console.log("[KnowledgePanel] uploading", f.name, f.size);
      const out = await uploadRag(f, undefined);
      console.log("[KnowledgePanel] result", out);
      total += out.added || 0;
    }
    toast?.(`Added ${total} chunks`);
    setFiles(null);
  } catch (e: any) {
    console.error("[KnowledgePanel] upload error", e);
    toast?.(e?.message || "Upload failed");
  } finally {
    setBusy(false);
  }
}

  async function doSearch() {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    try {
      const out = await searchRag(q, { sessionId, kChat: 6, kGlobal: 4, alpha: 0.5 });
      setHits(out.hits || []);
    } catch (e: any) {
      toast?.(e?.message || "Search failed");
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-3">
      <div className="w-full max-w-3xl rounded-2xl bg-white shadow-xl border overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center gap-2">
          <div className="font-semibold">Knowledge</div>
          <div className="ml-auto flex items-center gap-2">
            <button className="text-xs px-3 py-1.5 rounded border hover:bg-gray-50" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        <div className="p-4 grid gap-6 md:grid-cols-2">
          {/* Upload */}
          <div>
            <div className="font-medium mb-2">Upload documents</div>
            <input
              type="file"
              multiple
              className="block w-full text-sm"
              onChange={(e) => setFiles(e.target.files)}
            />
            <button
              className={`mt-2 text-sm px-3 py-1.5 rounded ${busy ? "opacity-60 cursor-not-allowed" : "bg-black text-white"}`}
              disabled={busy || !files || files.length === 0}
              onClick={doUpload}
            >
              {busy ? "Uploading…" : "Upload"}
            </button>
            <div className="text-[11px] text-gray-500 mt-2">
              Tip: CSV, TXT, MD, PDF (extracted as text) — per-chat or global depending on active session.
            </div>
          </div>

          {/* Search */}
          <div>
            <div className="font-medium mb-2">Quick search</div>
            <div className="flex gap-2">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Find in your knowledge…"
                className="flex-1 border rounded px-2 py-1.5 text-sm"
              />
              <button
                className={`text-sm px-3 py-1.5 rounded ${searching ? "opacity-60 cursor-wait" : "border hover:bg-gray-50"}`}
                onClick={doSearch}
                disabled={searching}
              >
                {searching ? "Searching…" : "Search"}
              </button>
            </div>

            <ul className="mt-3 space-y-2 max-h-64 overflow-auto">
              {hits.map((h, i) => (
                <li key={i} className="p-2 border rounded bg-gray-50">
                  <div className="text-[11px] text-gray-500 mb-1">
                    {h.source || "uploaded"} • score {h.score.toFixed(3)}
                  </div>
                  <div className="text-sm whitespace-pre-wrap">{h.text}</div>
                </li>
              ))}
              {!hits.length && (
                <li className="text-xs text-gray-500">No results yet.</li>
              )}
            </ul>
          </div>
        </div>

        <div className="px-4 py-3 border-t text-[11px] text-gray-500">
          When you chat, top results are injected automatically as “Local knowledge”.
        </div>
      </div>
    </div>
  );
}
