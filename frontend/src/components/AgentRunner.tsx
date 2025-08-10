import { useState } from "react";

export default function AgentRunner() {
  const [prompt, setPrompt] = useState<string>("");
  const [response, setResponse] = useState<string>("");

  const runAgent = async () => {
  if (!prompt) return;
  try {
    const res = await fetch("https://1c772e4eab90.ngrok-free.app", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });

    if (!res.ok) {
      throw new Error(`Server error: ${res.status}`);
    }

    const text = await res.text(); // read raw text
    try {
      // If it's JSON, parse it
      const parsed = JSON.parse(text);
      setResponse(parsed.response || text);
    } catch {
      // Otherwise, just show plain text
      setResponse(text);
    }
  } catch (err) {
    console.error(err);
    setResponse("Error generating response");
  }
};

  return (
    <div className="max-w-xl mx-auto p-6 bg-white rounded shadow-md">
      <h2 className="text-2xl font-semibold mb-4">Your Local AI Assistant</h2>

      <div className="mb-4">
        <label className="block mb-1 font-medium">Prompt</label>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Enter prompt here"
          className="w-full border border-gray-300 rounded px-3 py-2"
          rows={4}
        />
      </div>

      <button
        onClick={runAgent}
        className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700"
      >
        Run Agent
      </button>

      <div className="mt-4">
        <label className="block mb-1 font-medium">Response</label>
        <pre className="whitespace-pre-wrap bg-gray-100 p-4 rounded">
          {response}
        </pre>
      </div>
    </div>
  );
}
