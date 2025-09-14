import { PanelLeftOpen, Loader2, Power, ChevronDown } from "lucide-react";

type Props = {
  sidebarOpen: boolean;
  onShowSidebar: () => void;
  title?: string;

  modelLoaded: boolean;
  modelName?: string | null;
  busy?: boolean;

  onOpenModelPicker?: () => void;
  onEjectModel?: () => void;
};

export default function DesktopHeader({
  sidebarOpen,
  onShowSidebar,
  title = "Local AI Model",
  modelLoaded,
  modelName,
  busy = false,
  onOpenModelPicker,
  onEjectModel,
}: Props) {
  return (
    <div className="hidden md:flex h-14 shrink-0 items-center justify-between px-4 border-b bg-white">
      <div className="flex items-center gap-2">
        {!sidebarOpen && (
          <button
            className="h-9 w-9 inline-flex items-center justify-center rounded-lg border hover:bg-gray-50"
            onClick={onShowSidebar}
            aria-label="Show sidebar"
            title="Show sidebar"
          >
            <PanelLeftOpen className="w-4 h-4" />
          </button>
        )}
        <div className="font-semibold">{title}</div>
      </div>

      <div className="flex items-center">
        {!modelLoaded ? (
          <button
            type="button"
            onClick={() => onOpenModelPicker?.()}
            className="inline-flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg border hover:bg-gray-50"
            title="Select a model to load (Ctrl + L)"
          >
            <span className="h-2.5 w-2.5 rounded-full bg-gray-300" />
            <span className="whitespace-nowrap">Select a model to load</span>
            <ChevronDown className="w-4 h-4 opacity-60" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => onOpenModelPicker?.()}
            className="inline-flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg border hover:bg-gray-50"
            title="Change model (Ctrl + L)"
          >
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
            <span className="truncate max-w-[32ch]" title={modelName || "Model loaded"}>
              {modelName || "Model loaded"}
            </span>
            <ChevronDown className="w-4 h-4 opacity-60" />
          </button>
        )}
      </div>

      <div className="flex items-center gap-2">
        {busy ? (
          <div className="inline-flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg border bg-gray-50">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>Working…</span>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => onEjectModel?.()}
            disabled={!modelLoaded}
            className={`inline-flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg border ${
              modelLoaded ? "hover:bg-gray-50" : "opacity-60 cursor-not-allowed"
            }`}
            title={modelLoaded ? "Eject model" : "No model loaded"}
          >
            <Power className="w-4 h-4" />
            <span>Eject</span>
          </button>
        )}
      </div>
    </div>
  );
}
