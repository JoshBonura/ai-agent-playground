// frontend/src/components/ModelPicker/ModelPickerList.tsx
import {
  useEffect,
  useMemo,
  useRef,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  HardDrive,
  Loader2,
  Search,
} from "lucide-react";
import WorkerAdvancedPanel from "./WorkerAdvancedPanel";
import type { ModelFile } from "../../api/models";
import type { LlamaKwargs } from "../../api/modelWorkers";
import { useI18n } from "../../i18n/i18n";

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
  busyPaths: string[]; // keep for Enter key handler
  onLoad: (m: ModelFile) => void;
  expandedPath: string | null;
  setExpandedPath: Dispatch<SetStateAction<string | null>>;
  advDraft: LlamaKwargs;
  setAdvDraft: Dispatch<SetStateAction<LlamaKwargs>>;
  rememberAdv: boolean;
  setRememberAdv: (b: boolean) => void;
  onLoadAdvanced: (m: ModelFile) => void;
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
  busyPaths,
  onLoad,
  expandedPath,
  setExpandedPath,
  advDraft,
  setAdvDraft,
  rememberAdv,
  setRememberAdv,
  onLoadAdvanced,
  onClose,
}: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const { t } = useI18n();

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
          return sortDir === "asc"
            ? a.sizeBytes - b.sizeBytes
            : b.sizeBytes - a.sizeBytes;
        case "name":
          return sortDir === "asc"
            ? a.name.localeCompare(b.name)
            : b.name.localeCompare(a.name);
        case "recency":
        default:
          return sortDir === "asc"
            ? a.name.localeCompare(b.name)
            : b.name.localeCompare(a.name);
      }
    });
    return list;
  }, [models, query, sortKey, sortDir]);

  // Esc to close, Enter to quick-load first visible (if not busy)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Enter") {
        const first = filteredSorted[0];
        if (first && !busyPaths.includes(first.path)) onLoad(first);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [filteredSorted, busyPaths, onClose, onLoad]);

  // Autofocus search
  useEffect(() => {
    const tmr = setTimeout(() => inputRef.current?.focus(), 50);
    return () => clearTimeout(tmr);
  }, []);

  return (
    <>
      {/* Search + sort */}
      <div className="p-3 border-b bg-gray-50/60">
        <div className="flex items-center gap-2">
          <div className="flex-1 relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("modelPicker.search_placeholder")}
              className="w-full pl-9 pr-3 py-2 rounded-lg border bg-white text-sm"
            />
          </div>
          <div className="flex items-center gap-1">
            <button
              className="inline-flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg border hover:bg-gray-50"
              onClick={() =>
                setSortKey((k) =>
                  k === "recency" ? "size" : k === "size" ? "name" : "recency",
                )
              }
            >
              {sortKey === "recency"
                ? t("modelPicker.sort_recency")
                : sortKey === "size"
                ? t("modelPicker.sort_size")
                : t("modelPicker.sort_name")}
            </button>
            <button
              className="inline-flex items-center text-sm px-2 py-2 rounded-lg border hover:bg-gray-50"
              onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}
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
            {t("common.loading")}
          </div>
        )}
        {!!err && (
          <div className="flex items-center gap-2 text-sm text-red-600 mb-3">
            <AlertCircle className="w-4 h-4" />
            {err}
          </div>
        )}
        {!loading && filteredSorted.length === 0 && (
          <div className="text-sm text-gray-600">
            {t("modelPicker.list_none")}
          </div>
        )}

        <div className="space-y-2">
          {filteredSorted.map((m) => {
            const isOpen = expandedPath === m.path;
            return (
              <div key={m.path} className="rounded-lg border">
                <div className="p-3 flex items-center justify-between">
                  <div className="min-w-0 flex items-center gap-2">
                    <button
                      className="p-1 rounded hover:bg-gray-100"
                      onClick={() => setExpandedPath(isOpen ? null : m.path)}
                    >
                      {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </button>
                    <HardDrive className="w-4 h-4 text-gray-500" />
                    <div className="truncate ml-1">
                      <div className="truncate font-medium">{m.name}</div>
                      <div className="text-xs text-gray-500 truncate">
                        {m.rel || m.path}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="text-xs text-gray-500">
                      {t("modelPicker.list_size", {
                        size: formatGBNumber(m.sizeBytes),
                      })}
                    </div>
                    <button
                      onClick={() => onLoad(m)}
                      className="text-xs px-3 py-1.5 rounded border hover:bg-gray-100"
                    >
                      {t("modelPicker.load")}
                    </button>
                  </div>
                </div>

                {isOpen && (
                  <div className="border-t">
                    <WorkerAdvancedPanel
                      modelKey={m.path}
                      value={advDraft}
                      onChange={setAdvDraft}
                      remember={rememberAdv}
                      setRemember={setRememberAdv}
                    />
                    <div className="px-3 py-2 flex items-center justify-end gap-2">
                      <button
                        className="text-xs px-3 py-1.5 rounded border hover:bg-gray-100"
                        onClick={() => setExpandedPath(null)}
                      >
                        {t("common.cancel")}
                      </button>
                      <button
                        className="text-xs px-3 py-1.5 rounded bg-black text-white"
                        onClick={() => onLoadAdvanced(m)}
                      >
                        {t("modelPicker.load_with_settings")}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

function formatGBNumber(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(gb);
}
