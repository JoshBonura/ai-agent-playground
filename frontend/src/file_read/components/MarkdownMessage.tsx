import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github.css"; // light theme with token colors
import { Copy, Check } from "lucide-react";

type Props = { text: string };

export default function MarkdownMessage({ text }: Props) {
  return (
    <>
      {/* keep pre spacing at zero; don't overwrite token colors */}
      <style>{`
        pre { margin: 0 !important; padding: 0 !important; background: transparent !important; }
        pre code { display: block; margin: 0 !important; padding: 0 !important; }
        .hljs { background: transparent !important; }
      `}</style>

      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          code({
            inline,
            className,
            children,
            ...props
          }: {
            inline?: boolean;
            className?: string;
            children?: React.ReactNode;
          }) {
            const [copied, setCopied] = useState(false);
            const raw = String(children ?? "");
            const lang = (className || "").replace("language-", "");

            if (inline) {
              return (
                <code
                  className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-900 font-mono text-[14px]"
                  {...props}
                >
                  {children}
                </code>
              );
            }

            const onCopy = async () => {
              try {
                await navigator.clipboard.writeText(raw);
                setCopied(true);
                setTimeout(() => setCopied(false), 4000);
              } catch {}
            };

            return (
              <div className="relative w-full">
                <pre className="m-0 p-0 w-full overflow-x-auto rounded-md border border-gray-300">
                  {/* Let hljs theme color tokens; no text color override here */}
                  <code className={`${className ?? ""} hljs font-mono text-sm`} {...props}>
                    {children}
                  </code>
                </pre>

                <div className="absolute top-2 right-2 flex items-center gap-1">
                  {lang && (
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-200 text-gray-700">
                      {lang}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={onCopy}
                    title={copied ? "Copied!" : "Copy"}
                    className="inline-flex items-center justify-center w-7 h-7 rounded bg-gray-200 text-gray-600 hover:bg-gray-300 transition"
                  >
                    {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  </button>
                </div>
              </div>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </>
  );
}
