// pages/AgentRunner.tsx
import Appintro from "../components/AppIntro";
import ChatContainer from "../components/ChatContainer";

export default function AgentRunner() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="mx-auto max-w-3xl p-4">
        {/* One card controls spacing/height */}
        <div className="bg-white rounded-xl shadow-sm border flex flex-col h-[95vh]">
          {/* Header / Intro */}
          <div>
            <Appintro />
          </div>

          {/* Chat grows to fill */}
          <div className="flex-1 min-h-0"> 
            <ChatContainer />
          </div>

          {/* Footer */}

        </div>
      </div>
    </div>
  );
}
