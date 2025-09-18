// frontend/src/file_read/pages/AgentRunnerView.tsx
import DesktopHeader from "../components/DesktopHeader";
import MobileDrawer from "../components/MobileDrawer";
import Toast from "../shared/ui/Toast";
import ChatSidebar from "../components/ChatSidebar/ChatSidebar";
import ChatContainer from "../components/ChatContainer";
import SettingsPanel from "../components/SettingsPanel";
import KnowledgePanel from "../components/KnowledgePanel";
import ModelPicker from "../components/ModelPicker/ModelPicker";
import type { Attachment } from "../types/chat";

type ChatApi = {
  messages: any[];
  input: string;
  setInput: (v: string) => void;
  loading: boolean;
  queued?: boolean;
  send: (text?: string, attachments?: Attachment[]) => Promise<void>;
  stop: () => void;
  runMetrics?: any;
  runJson?: any;
  setSessionId: (id: string) => void;
  sessionIdRef: { current: string | null };
  clearMetrics?: () => void;
  loadHistory: (id: string) => Promise<void>;
  reset: () => void;
};

type Props = {
  // sidebar & drawer
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  openMobileDrawer: () => void;
  closeMobileDrawer: () => void;

  // chat & state
  chat: ChatApi;
  autoFollow: boolean;
  refreshKey: number;
  toast: string | null;

  // model
  modelLoaded: boolean;
  modelName: string | null;
  showModelPicker: boolean;
  setShowModelPicker: (v: boolean) => void;
  onEjectModel: () => Promise<void> | void;
  onHealthRefresh: () => Promise<void> | void;

  // panels
  showSettings: boolean;
  setShowSettings: (v: boolean) => void;
  showKnowledge: boolean;
  setShowKnowledge: (v: boolean) => void;

  // handlers
  onOpenSession: (id: string) => Promise<void>;
  onNewChat: () => Promise<void>;
  onCancelSessions: (ids: string[]) => Promise<void>;
  onDeleteMessages: (clientIds: string[]) => Promise<void>;
  safeSend: (text?: string, attachments?: Attachment[]) => Promise<void>;
  showToast: (msg: string) => void;
};

export default function AgentRunnerView({
  // sidebar & drawer
  sidebarOpen,
  setSidebarOpen,
  openMobileDrawer,
  closeMobileDrawer,

  // chat & state
  chat,
  autoFollow,
  refreshKey,
  toast,

  // model
  modelLoaded,
  modelName,
  showModelPicker,
  setShowModelPicker,
  onEjectModel,
  onHealthRefresh,

  // panels
  showSettings,
  setShowSettings,
  showKnowledge,
  setShowKnowledge,

  // handlers
  onOpenSession,
  onNewChat,
  onCancelSessions,
  onDeleteMessages,
  safeSend,
  showToast,
}: Props) {
  return (
    <div className="h-screen w-full flex bg-gray-50">
      {sidebarOpen && (
        <div className="hidden md:flex h-full">
          <ChatSidebar
            onOpen={onOpenSession}
            onNew={onNewChat}
            refreshKey={refreshKey}
            activeId={chat.sessionIdRef.current || undefined}
            onHideSidebar={() => setSidebarOpen(false)}
            onCancelSessions={onCancelSessions}
          />
        </div>
      )}

      <MobileDrawer
        onOpenSession={onOpenSession}
        onNewChat={onNewChat}
        refreshKey={refreshKey}
        activeId={chat.sessionIdRef.current || undefined}
        openMobileDrawer={openMobileDrawer}
        closeMobileDrawer={closeMobileDrawer}
      />
      <div className="md:hidden h-14 shrink-0" />

      <div className="flex-1 min-w-0 flex flex-col">
        <DesktopHeader
          sidebarOpen={sidebarOpen}
          onShowSidebar={() => setSidebarOpen(true)}
          modelLoaded={modelLoaded}
          modelName={modelName}
          busy={false}
          onOpenModelPicker={() => setShowModelPicker(true)}
          onEjectModel={onEjectModel}
        />

        {!modelLoaded && (
          <div className="px-3 md:px-6 mt-2">
            <div className="mx-auto max-w-3xl md:max-w-4xl">
              <div className="rounded-lg border bg-amber-50 text-amber-900 text-sm px-3 py-2">
                No model is loaded. Click{" "}
                <button
                  className="ml-1 inline-flex items-center text-xs px-2 py-1 rounded border hover:bg-amber-100"
                  onClick={() => setShowModelPicker(true)}
                >
                  Select a model to load
                </button>{" "}
                to start chatting.
              </div>
            </div>
          </div>
        )}

        <div className="flex-1 min-h-0">
          <div className="h-full px-3 md:px-6">
            <div className="h-full w-full mx-auto max-w-3xl md:max-w-4xl relative">
              <div id="chat-scroll-container" className="h-full">
                <ChatContainer
                  messages={chat.messages}
                  input={chat.input}
                  setInput={chat.setInput}
                  loading={chat.loading}
                  queued={chat.queued}
                  send={safeSend}
                  stop={chat.stop}
                  runMetrics={chat.runMetrics}
                  runJson={chat.runJson}
                  onRefreshChats={() => {}}
                  onDeleteMessages={onDeleteMessages}
                  autoFollow={autoFollow}
                  sessionId={chat.sessionIdRef.current || undefined}
                />
              </div>
              <Toast message={toast} />
            </div>
          </div>
        </div>
      </div>

      {showModelPicker && (
        <ModelPicker
          open={showModelPicker}
          onClose={() => setShowModelPicker(false)}
          onLoaded={onHealthRefresh}
        />
      )}

      {showSettings && (
        <SettingsPanel
          sessionId={chat.sessionIdRef.current || undefined}
          onClose={() => setShowSettings(false)}
        />
      )}
      {showKnowledge && (
        <KnowledgePanel
          sessionId={chat.sessionIdRef.current || undefined}
          onClose={() => setShowKnowledge(false)}
          toast={showToast}
        />
      )}
    </div>
  );
}
