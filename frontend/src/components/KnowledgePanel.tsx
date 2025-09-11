import { useState, useEffect } from "react";
import {
  uploadRag,
  searchRag,
  listUploads,
  deleteUploadHard,
  type UploadRow,
} from "../data/ragApi";

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
  const [hits, setHits] = useState<
    { text: string; source?: string; score: number }[]
  >([]);
  const [searching, setSearching] = useState(false);

  const [scope, setScope] = useState<"all" | "session">("all");
  const [uploads, setUploads] = useState<UploadRow[]>([]);
  const [loadingUploads, setLoadingUploads] = useState(false);

  useEffect(() => {
    void refreshUploads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, sessionId]);

  async function refreshUploads() {
    setLoadingUploads(true);
    try {
      const out = await listUploads(sessionId, scope);
      setUploads(out.uploads || []);
    } catch (e: any) {
      toast?.(e?.message || "Failed to load uploads");
    } finally {
      setLoadingUploads(false);
    }
  }

  async function handleDeleteHard(source: string, ns?: string | null) {
    try {
      const res = await deleteUploadHard(source, ns ?? undefined);
      toast?.(
        `Removed ${res.removed} chunk${res.removed === 1 ? "" : "s"}. Remaining: ${res.remaining}`,
      );
      await refreshUploads();
    } catch (e: any) {
      toast?.(e?.message || "Delete failed");
    }
  }

  async function doUpload() {
    if (!files || !files.length) return;
    setBusy(true);
    try {
      let total = 0;
      for (const f of Array.from(files)) {
        const out = await uploadRag(f, undefined);
        total += (out as any)?.added || 0;
      }
      toast?.(`Added ${total} chunk${total === 1 ? "" : "s"}`);
      setFiles(null);
      await refreshUploads();
    } catch (e: any) {
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
      const out = await searchRag(q, {
        sessionId,
        kChat: 6,
        kGlobal: 4,
        alpha: 0.5,
      });
      setHits(out.hits || []);
    } catch (e: any) {
      toast?.(e?.message || "Search failed");
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-3">
      <div className="w-full max-w-5xl rounded-2xl bg-white shadow-xl border overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center gap-2">
          <div className="font-semibold">Knowledge</div>
          <div className="ml-auto flex items-center gap-2">
            <button
              className="text-xs px-3 py-1.5 rounded border hover:bg-gray-50"
              onClick={onClose}
            >
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
              Tip: CSV, TXT, MD, PDF (text extracted). Uploads can be global or
              per chat.
            </div>

            <div className="mt-6">
              <div className="flex items-center gap-2 mb-2">
                <div className="font-medium">Your uploads</div>
                <select
                  className="ml-auto border rounded px-2 py-1 text-xs"
                  value={scope}
                  onChange={(e) =>
                    setScope(e.target.value as "all" | "session")
                  }
                  title="Scope"
                >
                  <option value="all">All (global + this chat)</option>
                  <option value="session">This chat only</option>
                </select>
                <button
                  className="text-xs px-2 py-1 rounded border hover:bg-gray-50"
                  onClick={refreshUploads}
                  disabled={loadingUploads}
                >
                  {loadingUploads ? "Refreshing…" : "Refresh"}
                </button>
              </div>

              <ul className="space-y-2 max-h-64 overflow-auto">
                {uploads.length === 0 && (
                  <li className="text-xs text-gray-500">No uploads yet.</li>
                )}
                {uploads.map((u, i) => (
                  <li
                    key={`${u.source}-${u.sessionId ?? "global"}-${i}`}
                    className="p-2 border rounded bg-gray-50"
                  >
                    <div className="flex items-center gap-2">
                      <div className="font-mono text-xs break-all">
                        {u.source}
                      </div>
                      <span className="text-[11px] text-gray-500">
                        {u.sessionId ? "session" : "global"} • {u.chunks} chunk
                        {u.chunks === 1 ? "" : "s"}
                      </span>
                      <button
                        className="ml-auto text-xs px-2 py-1 rounded border hover:bg-gray-100"
                        title="Delete (hard delete by Source)"
                        onClick={() =>
                          handleDeleteHard(u.source, u.sessionId ?? undefined)
                        }
                      >
                        Delete
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
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
                    {h.source || "uploaded"} • score{" "}
                    {Number.isFinite(h.score) ? h.score.toFixed(3) : "—"}
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
          “Delete” performs a hard delete: removes chunks for that Source and
          rebuilds the index.
        </div>
      </div>
    </div>
  );
}
