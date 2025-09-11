// frontend/src/file_read/components/MarkdownMessage.tsx
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github.css";
import CodeCopyButton from "../../shared/ui/CodeCopyButton";

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
        rehypePlugins={[
          [rehypeHighlight, { detect: true, ignoreMissing: true }],
        ]}
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

            return (
              <div className="relative w-full">
                <pre className="m-0 p-0 w-full overflow-x-auto rounded-md border border-gray-300">
                  {/* Let hljs theme color tokens; no text color override here */}
                  <code
                    className={`${className ?? ""} hljs font-mono text-sm`}
                    {...props}
                  >
                    {children}
                  </code>
                </pre>

                <div className="absolute top-2 right-2 flex items-center gap-1">
                  {lang && (
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-200 text-gray-700">
                      {lang}
                    </span>
                  )}
                  <CodeCopyButton text={raw} />
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
