export default function ChatBubble({
  role,
  text,
}: {
  role: "user" | "assistant";
  text: string;
}) {
  const isUser = role === "user";
  const showPlaceholder = role === "assistant" && !text;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] break-words whitespace-pre-wrap rounded-2xl px-4 py-2 shadow-sm ${
          isUser ? "bg-black text-white" : "bg-white border"
        }`}
      >
        {showPlaceholder ? <span className="opacity-50">…</span> : text}
      </div>
    </div>
  );
}
