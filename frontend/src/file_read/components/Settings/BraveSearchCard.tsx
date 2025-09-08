import { useEffect, useState } from "react";
import { getEffective, patchOverrides } from "../../data/settingsApi";

export default function BraveSearchCard() {
  const [loading, setLoading] = useState(true);
  const [, setProvider] = useState("brave");
  const [useWorker, setUseWorker] = useState(false);
  const [workerUrl, setWorkerUrl] = useState("");

  // we don’t prefill the API key for security; we only show a “present” flag
  const [hasKey, setHasKey] = useState<boolean>(false);
  const [apiKey, setApiKey] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const eff = await getEffective();
        setProvider(String(eff.web_search_provider ?? "brave"));
        setWorkerUrl(String(eff.brave_worker_url ?? ""));
        setUseWorker(Boolean(eff.brave_worker_url));
        // backend will mask the key and expose only boolean presence
        setHasKey(Boolean(eff.brave_api_key_present));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function save() {
    const patch: Record<string, any> = {
      web_search_provider: "brave",
      // if worker is used, clear server-side key (we’ll route via worker instead)
      brave_api_key: useWorker ? "" : apiKey,
      brave_worker_url: useWorker ? workerUrl : "",
    };
    await patchOverrides(patch);
    // don’t keep key in memory after save
    setApiKey("");
    setHasKey(!useWorker && !!patch.brave_api_key);
  }

  if (loading) return null;

  return (
    <div className="rounded-2xl p-4 border">
      <h3 className="font-semibold mb-2">Web Search (Brave)</h3>

      <div className="mb-3">
        <label className="block text-sm mb-1">Route via Cloudflare Worker</label>
        <input
          type="checkbox"
          checked={useWorker}
          onChange={(e) => setUseWorker(e.target.checked)}
        />
      </div>

      {useWorker ? (
        <div className="mb-3">
          <label className="block text-sm mb-1">Worker URL</label>
          <input
            className="w-full border rounded p-2"
            placeholder="https://your-worker.workers.dev/brave"
            value={workerUrl}
            onChange={(e) => setWorkerUrl(e.target.value)}
          />
          <p className="text-xs text-muted-foreground mt-1">
            Your Worker holds the Brave API key. The app doesn’t store it.
          </p>
        </div>
      ) : (
        <div className="mb-3">
          <label className="block text-sm mb-1">Brave API Key</label>
          <input
            className="w-full border rounded p-2"
            placeholder="X-Subscription-Token"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            spellCheck={false}
          />
          <p className="text-xs text-muted-foreground mt-1">
            {hasKey ? "Key is stored on the server." : "No key stored yet."}
          </p>
        </div>
      )}

      <button className="mt-2 px-3 py-2 rounded bg-black text-white" onClick={save}>
        Save
      </button>
    </div>
  );
}
