import {
  useEffect,
  useMemo,
  useRef,
  type Dispatch,
  type SetStateAction,
} from "react";
import { AlertCircle, ChevronDown, HardDrive, Loader2, Search } from "lucide-react";
import type { ModelFile } from "../../api/models";

type Props = {
  loading: boolean;
  err: string | null;
  models: ModelFile[];
  query: string;
  setQuery: Dispatch<SetStateAction<string>>;
  sortKey: "recency" | "size" | "name";
  setSortKey: Dispatch<SetStateAction<"recency" | "size" | "name">>;
  sortDir: "asc" | "desc";
  setSortDir: Dispatch<SetStateAction<"asc" | "desc">>;
  busyPath: string | null;
  onLoad: (m: ModelFile) => void;   // ← Load = spawn
  onClose: () => void;
};

export default function ModelPickerList({
  loading,
  err,
  models,
  query,
  setQuery,
  sortKey,
  setSortKey,
  sortDir,
  setSortDir,
  busyPath,
  onLoad,
  onClose,
}: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  const filteredSorted = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = !q
      ? models.slice()
      : models.filter(
          (m) =>
            m.name.toLowerCase().includes(q) ||
            m.path.toLowerCase().includes(q) ||
            (m.rel || "").toLowerCase().includes(q),
        );

    list.sort((a, b) => {
      switch (sortKey) {
        case "size":
          return sortDir === "asc" ? a.sizeBytes - b.sizeBytes : b.sizeBytes - a.sizeBytes;
        case "name":
          return sortDir === "asc" ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
        case "recency":
        default:
          return sortDir === "asc" ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
      }
    });
    return list;
  }, [models, query, sortKey, sortDir]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Enter") {
        const first = filteredSorted[0];
        if (first && !busyPath) onLoad(first);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [filteredSorted, busyPath, onClose, onLoad]);

  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, []);

  return (
    <>
      {/* Search + sort row */}
      <div className="p-3 border-b bg-gray-50/60">
        <div className="flex items-center gap-2">
          <div className="flex-1 relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type to filter models…"
              className="w-full pl-9 pr-3 py-2 rounded-lg border bg-white text-sm"
            />
          </div>
          <div className="flex items-center gap-1">
            <button
              className="inline-flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg border hover:bg-gray-50"
              onClick={() =>
                setSortKey((k) => (k === "recency" ? "size" : k === "size" ? "name" : "recency"))
              }
              title="Toggle sort key (Recency → Size → Name)"
            >
              {sortKey === "recency" ? "Recency" : sortKey === "size" ? "Size" : "Name"}{" "}
              <ChevronDown className="w-4 h-4 opacity-60" />
            </button>
            <button
              className="inline-flex items-center text-sm px-2 py-2 rounded-lg border hover:bg-gray-50"
              onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}
              title={`Sort ${sortDir === "asc" ? "ascending" : "descending"}`}
            >
              {sortDir === "asc" ? "↑" : "↓"}
            </button>
          </div>
        </div>
      </div>

      {/* List body */}
      <div className="p-3 max-h-[60vh] overflow-auto">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading models…
          </div>
        )}

        {!!err && (
          <div className="flex items-center gap-2 text-sm text-red-600 mb-3">
            <AlertCircle className="w-4 h-4" />
            {err}
          </div>
        )}

        {!loading && filteredSorted.length === 0 && (
          <div className="text-sm text-gray-600">No models match your filter.</div>
        )}

        <div className="space-y-2">
          {filteredSorted.map((m) => {
            const isBusy = busyPath === m.path;
            return (
              <div key={m.path} className="rounded-lg border p-3 flex items-center justify-between">
                <div className="min-w-0 flex items-center gap-3">
                  <HardDrive className="w-4 h-4 text-gray-500" />
                  <div className="truncate">
                    <div className="truncate font-medium" title={m.name}>
                      {m.name}
                    </div>
                    <div className="text-xs text-gray-500 truncate" title={m.path}>
                      {m.rel || m.path}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="text-xs text-gray-500">{bytesToGB(m.sizeBytes)}</div>
                  <button
                    onClick={() => onLoad(m)}
                    disabled={!!busyPath}
                    className={`text-xs px-3 py-1.5 rounded border ${
                      isBusy ? "opacity-60 cursor-wait" : "hover:bg-gray-100"
                    }`}
                    title="Load model (spawns a worker)"
                  >
                    {isBusy ? "Loading…" : "Load"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

function bytesToGB(n: number): string {
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
