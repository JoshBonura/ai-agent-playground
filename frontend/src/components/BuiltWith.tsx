export default function BuiltWith() {
  return (
    <div className="bg-gray-50 rounded shadow p-6">
      <h3 className="text-lg font-semibold mb-3">Built With</h3>
      <ul className="list-disc list-inside space-y-1 text-gray-700">
        <li><strong>Frontend:</strong> React (TypeScript), Vite, Tailwind CSS</li>
        <li><strong>Backend (Java):</strong> Spring Boot, Spring Web, H2 Database, Maven</li>
        <li><strong>AI Model Layer (Python):</strong> FastAPI, llama-cpp-python, uvicorn</li>
        <li><strong>Search & Retrieval:</strong> Elasticsearch, Docker <em>(in development)</em></li>
        <li><strong>Other Tools:</strong> Node.js + npm, cURL, Visual Studio Code</li>
      </ul>
    </div>
  );
}
