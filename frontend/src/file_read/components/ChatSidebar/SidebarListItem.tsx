import { firstLineSmart } from "../../shared/lib/text";
import type { ChatRow } from "../../types/chat";

export default function SidebarListItem({
  c, isActive, isEditing, isChecked, onToggle, onOpen,
}: {
  c: ChatRow;
  isActive: boolean;
  isEditing: boolean;
  isChecked: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const displayTitle =
    (c.title && c.title.trim()) ||
    firstLineSmart(c.lastMessage || "", 48) ||
    "New Chat";
  const preview = c.lastMessage ? firstLineSmart(c.lastMessage, 120) : "";

  return (
    <li>
      <div
        className={`w-full flex items-start gap-2 px-2 py-2 rounded ${
          isActive ? "bg-black text-white" : "hover:bg-gray-50"
        }`}
      >
        {isEditing && (
          <input
            type="checkbox"
            checked={isChecked}
            onChange={onToggle}
            className="mt-1"
            aria-label={`Select chat ${displayTitle}`}
          />
        )}
        <button
          className="text-left flex-1"
          aria-current={isActive ? "true" : undefined}
          onClick={() => { if (!isEditing) onOpen(); }}
          title={displayTitle}
        >
          <div className="font-medium truncate">{displayTitle}</div>
          {preview && (
            <div className={`text-xs line-clamp-2 ${isActive ? "text-white/80" : "text-gray-500"}`}>
              {preview}
            </div>
          )}
          <div className="text-[10px] mt-1 opacity-60">
            {new Date(c.updatedAt).toLocaleString()}
          </div>
        </button>
      </div>
    </li>
  );
}
