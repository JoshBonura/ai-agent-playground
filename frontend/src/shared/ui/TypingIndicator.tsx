// components/TypingIndicator.tsx
export default function TypingIndicator() {
  return (
    <div className="flex items-start gap-2">
      {/* Optional avatar spot */}
      <div className="h-8 w-8 rounded-full bg-gray-200 shrink-0" />
      <div className="px-3 py-2 rounded-lg bg-gray-100 text-gray-600">
        <span className="inline-flex gap-1">
          <span className="h-2 w-2 rounded-full bg-gray-400 animate-bounce [animation-delay:-0.2s]" />
          <span className="h-2 w-2 rounded-full bg-gray-400 animate-bounce [animation-delay:-0.1s]" />
          <span className="h-2 w-2 rounded-full bg-gray-400 animate-bounce" />
        </span>
      </div>
    </div>
  );
}
