export default function Toast({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="pointer-events-none fixed bottom-4 left-1/2 -translate-x-1/2 z-50">
      <div className="px-3 py-2 rounded-lg bg-black text-white text-xs shadow-lg">
        {message}
      </div>
    </div>
  );
}
