// frontend/src/file_read/components/CodeCopyButton.tsx
import { Copy, Check } from "lucide-react";
import { useState } from "react";

export default function CodeCopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function onCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  }
  return (
    <button
      type="button"
      onClick={onCopy}
      title={copied ? "Copied!" : "Copy"}
      className="inline-flex items-center justify-center w-7 h-7 rounded bg-gray-200 text-gray-600 hover:bg-gray-300 transition"
    >
      {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
    </button>
  );
}
