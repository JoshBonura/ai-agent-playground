import { PanelLeftClose, Plus, Pencil, Trash2 } from "lucide-react";

export default function SidebarHeader({
  isEditing, setIsEditing, newPending, onNew, onHideSidebar,
  selectedCount, deleting, onDelete,
}: {
  isEditing: boolean;
  setIsEditing: (v: boolean) => void;
  newPending: boolean;
  onNew: () => Promise<void>;
  onHideSidebar?: () => void;
  selectedCount: number;
  deleting: boolean;
  onDelete: () => void;
}) {
  return (
    <div className="sticky top-0 z-10 bg-white border-b">
      <div className="flex items-center justify-between px-3 py-2">
        <div className="text-[11px] md:text-xs uppercase text-gray-500">Chats</div>
        <div className="flex items-center gap-2">
          <button
            className={`h-9 px-3 inline-flex items-center gap-2 justify-center rounded border ${
              newPending ? "opacity-50 cursor-not-allowed" : ""
            }`}
            onClick={async () => { if (!newPending) await onNew(); }}
            title="New chat"
            disabled={newPending}
          >
            <Plus className="w-4 h-4" />
            <span className="text-xs md:text-[11px] leading-none">New</span>
          </button>

          <button
            className="h-9 px-3 inline-flex items-center gap-2 justify-center rounded border"
            onClick={() => setIsEditing(!isEditing)}
            aria-pressed={isEditing}
            title={isEditing ? "Exit edit mode" : "Edit chats"}
          >
            <Pencil className="w-4 h-4" />
            <span className="text-xs md:text-[11px] leading-none">
              {isEditing ? "Done" : "Edit"}
            </span>
          </button>

          {onHideSidebar && (
            <button
              className="hidden md:inline-flex h-9 w-9 items-center justify-center rounded border"
              onClick={onHideSidebar}
              title="Hide sidebar"
              aria-label="Hide sidebar"
            >
              <PanelLeftClose className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {isEditing && (
        <div className="px-3 py-2 border-t bg-white flex items-center gap-3">
          <div className="text-sm text-gray-600">{selectedCount} selected</div>
          <button
            className={`ml-auto inline-flex items-center gap-2 text-sm px-3 py-1 rounded ${
              selectedCount && !deleting
                ? "bg-red-600 text-white"
                : "bg-gray-200 text-gray-500 cursor-not-allowed"
            }`}
            disabled={!selectedCount || deleting}
            onClick={onDelete}
            title={selectedCount ? "Delete selected chats" : "Select chats to delete"}
          >
            <Trash2 className="w-4 h-4" />
            {deleting ? "Deleting…" : `Delete (${selectedCount})`}
          </button>
        </div>
      )}
    </div>
  );
}
