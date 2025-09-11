import { PanelLeftOpen } from "lucide-react";
import ChatSidebar from "./ChatSidebar/ChatSidebar";

export default function MobileDrawer({ ...props }) {
  const {
    onOpenSession,
    onNewChat,
    refreshKey,
    activeId,
    openMobileDrawer,
    closeMobileDrawer,
  } = props;

  return (
    <>
      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 bg-white border-b">
        <div className="h-14 flex items-center justify-between px-3">
          <button
            className="inline-flex items-center justify-center h-9 w-9 rounded-lg border hover:bg-gray-50"
            onClick={() => {
              openMobileDrawer();
            }}
            aria-label="Open sidebar"
            title="Open sidebar"
          >
            <PanelLeftOpen className="w-4 h-4" />
          </button>
          <div className="font-semibold">Local AI Model</div>
          <div className="w-9" />
        </div>
      </div>

      {/* Backdrop */}
      <div
        id="mobile-backdrop"
        className="md:hidden fixed inset-0 z-40 bg-black/40 hidden"
        onClick={() => {
          closeMobileDrawer();
        }}
      />

      {/* Drawer */}
      <aside
        id="mobile-drawer"
        role="dialog"
        aria-modal="true"
        className="
          md:hidden fixed inset-y-0 left-0 z-50
          w-80 max-w-[85vw]
          bg-white border-r shadow-xl
          hidden animate-[slideIn_.2s_ease-out]
          h-[100dvh] pb-safe flex flex-col
        "
      >
        <div className="h-14 flex items-center justify-between px-3 border-b">
          <div className="font-medium">Chats</div>
          <button
            className="h-9 w-9 inline-flex items-center justify-center rounded-lg border hover:bg-gray-50"
            onClick={() => {
              closeMobileDrawer();
            }}
            aria-label="Close sidebar"
          >
            <span className="rotate-45 text-xl leading-none">+</span>
          </button>
        </div>

        {/* Fill remaining height; ChatSidebar manages its own scrolling */}
        <div className="flex-1 min-h-0 overflow-hidden">
          <ChatSidebar
            onOpen={async (id) => {
              await onOpenSession(id);
              closeMobileDrawer();
            }}
            onNew={async () => {
              await onNewChat();
              closeMobileDrawer();
            }}
            refreshKey={refreshKey}
            activeId={activeId}
          />
        </div>
      </aside>

      <style>{`@keyframes slideIn{from{transform:translateX(-12px);opacity:.0}to{transform:translateX(0);opacity:1}}`}</style>
    </>
  );
}
