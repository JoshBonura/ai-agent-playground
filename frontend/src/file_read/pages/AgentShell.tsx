// frontend/src/file_read/pages/AgentShell.tsx
import DesktopHeader from "../components/DesktopHeader";
import MobileDrawer from "../components/MobileDrawer";
import ChatSidebar from "../components/ChatSidebar/ChatSidebar";
import ChatContainer from "../components/ChatContainer";

export default function AgentShell({
  sidebarOpen, setSidebarOpen,
  openMobileDrawer, closeMobileDrawer,
  refreshKey, activeId,
  onOpenSession, onNewChat,
  chatProps,
}: {
  sidebarOpen: boolean;
  setSidebarOpen: (v: boolean) => void;
  openMobileDrawer: () => void;
  closeMobileDrawer: () => void;
  refreshKey: number;
  activeId?: string;
  onOpenSession: (id: string) => Promise<void>;
  onNewChat: () => Promise<void>;
  chatProps: React.ComponentProps<typeof ChatContainer>;
}) {
  return (
    <div className="h-screen w-full flex bg-gray-50">
      {sidebarOpen && (
        <div className="hidden md:flex h-full">
          <ChatSidebar
            onOpen={onOpenSession}
            onNew={onNewChat}
            refreshKey={refreshKey}
            activeId={activeId}
            onHideSidebar={() => setSidebarOpen(false)}
          />
        </div>
      )}

      <MobileDrawer
        onOpenSession={onOpenSession}
        onNewChat={onNewChat}
        refreshKey={refreshKey}
        activeId={activeId}
        openMobileDrawer={openMobileDrawer}
        closeMobileDrawer={closeMobileDrawer}
      />
      <div className="md:hidden h-14 shrink-0" />

      <div className="flex-1 min-w-0 flex flex-col">
        <DesktopHeader
          sidebarOpen={sidebarOpen}
          onShowSidebar={() => setSidebarOpen(true)}
        />
        <div className="flex-1 min-h-0">
          <div className="h-full px-3 md:px-6">
            <div className="h-full w-full mx-auto max-w-3xl md:max-w-4xl relative">
              <ChatContainer {...chatProps} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
