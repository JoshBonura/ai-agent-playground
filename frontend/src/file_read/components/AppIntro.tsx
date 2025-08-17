export default function AppIntro() {
  return (
    <div className="max-w-2xl mx-auto p-6 bg-gray-50 rounded shadow mb-6 hidden sm:block">
      <h1 className="text-3xl font-bold mb-4">Welcome to My Local Model</h1>

      <p className="mb-3">
        Hi, I’m <strong>Josh Bonura</strong> — a <strong>Product Manager</strong> with hands‑on
        engineering and AI experience. This demo is a fully local, end‑to‑end AI app:
        when you submit a prompt, it goes through a <strong>Java 17 / Spring Boot</strong> backend,
        calls a <strong>Python FastAPI (Uvicorn)</strong> service running a <strong>LLaMA + Mistral</strong> model,
        and streams the response back to this <strong>React</strong> UI.
      </p>

      <p className="mb-3">
        It runs on my own PC with <strong>4GB VRAM</strong>, so it’s not cloud‑speed— but it demonstrates privacy, local inference, and a clean full‑stack integration.
        Try a prompt and hit <strong>Generate</strong> to see it in action.
      </p>

      <div className="mt-4">
        <div className="font-semibold mb-1">Links</div>
        <ul className="list-disc ml-5 space-y-1">
          <li>
            <a
              href="https://github.com/JoshBonura/ai-agent-playground"
              className="text-blue-600 underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub – ai-agent-playground
            </a>
          </li>
          <li>
            <a
              href="https://www.linkedin.com/in/josh-bonura/"
              className="text-blue-600 underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              LinkedIn – Josh Bonura
            </a>
          </li>
        </ul>
      </div>
    </div>
  );
}
