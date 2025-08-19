import { PanelLeftOpen } from "lucide-react";

export default function DesktopHeader({
  sidebarOpen,
  onShowSidebar,
  title = "Local AI Model",
}: {
  sidebarOpen: boolean;
  onShowSidebar: () => void;
  title?: string;
}) {
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
      <div />
    </div>
  );
}
