export default function ProgressBar({ pct, error }: { pct: number; error?: boolean }) {
  return (
    <div className="mt-2 h-1.5 w-full bg-gray-200 rounded">
      <div
        className={`h-1.5 rounded ${error ? "bg-red-500" : "bg-black"}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
