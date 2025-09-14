import { PanelLeftOpen, Loader2, Power, ChevronDown } from "lucide-react";

type Props = {
  sidebarOpen: boolean;
  onShowSidebar: () => void;
  title?: string;

  // Optional model UI (safe defaults so AgentRunner can omit them)
  modelLoaded?: boolean;
  modelName?: string | null;
  busy?: boolean;

  // Optional actions (if not provided, the center/right controls are hidden)
  onOpenModelPicker?: () => void;
  onEjectModel?: () => void;
};

export default function DesktopHeader({
  sidebarOpen,
  onShowSidebar,
  title = "Local AI Model",

  // defaults make these truly optional
  modelLoaded = false,
  modelName = null,
  busy = false,

  onOpenModelPicker,
  onEjectModel,
}: Props) {
  return (
    <div className="hidden md:flex h-14 shrink-0 items-center justify-between px-4 border-b bg-white">
      {/* Left: sidebar toggle + title */}
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

      {/* Center: model status / picker (only if a picker handler is supplied) */}
      <div className="flex items-center">
        {onOpenModelPicker ? (
          !modelLoaded ? (
            <button
              type="button"
              onClick={onOpenModelPicker}
              className="inline-flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg border hover:bg-gray-50"
              title="Select a model to load"
            >
              <span className="h-2.5 w-2.5 rounded-full bg-gray-300" />
              <span className="whitespace-nowrap">Select a model to load</span>
              <ChevronDown className="w-4 h-4 opacity-60" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onOpenModelPicker}
              className="inline-flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg border hover:bg-gray-50"
              title="Change model"
            >
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
              <span
                className="truncate max-w-[32ch]"
                title={modelName || "Model loaded"}
              >
                {modelName || "Model loaded"}
              </span>
              <ChevronDown className="w-4 h-4 opacity-60" />
            </button>
          )
        ) : (
          // If no picker handler, keep layout balanced with an empty spacer
          <div className="w-0" />
        )}
      </div>

      {/* Right: eject / busy indicator (only if an eject handler is supplied) */}
      <div className="flex items-center gap-2">
        {busy ? (
          <div className="inline-flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg border bg-gray-50">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>Working…</span>
          </div>
        ) : onEjectModel ? (
          <button
            type="button"
            onClick={onEjectModel}
            disabled={!modelLoaded}
            className={`inline-flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg border ${
              modelLoaded ? "hover:bg-gray-50" : "opacity-60 cursor-not-allowed"
            }`}
            title={modelLoaded ? "Unload model" : "No model loaded"}
          >
            <Power className="w-4 h-4" />
            <span>Eject</span>
          </button>
        ) : (
          <div className="w-0" />
        )}
      </div>
    </div>
  );
}
