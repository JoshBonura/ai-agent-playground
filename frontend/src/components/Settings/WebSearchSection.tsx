import { useEffect, useState } from "react";
import { getEffective, patchOverrides } from "../../data/settingsApi";

export default function WebSearchSection({
  onSaved,
}: {
  onSaved?: () => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [masked, setMasked] = useState(true);
  const [status, setStatus] = useState<null | { ok: boolean; msg: string }>(
    null,
  );

  useEffect(() => {
    (async () => {
      try {
        const eff = await getEffective();
        setApiKey(eff.brave_api_key || "");
      } catch {
        // fallback if no settings
      }
    })();
  }, []);

  async function save() {
    try {
      await patchOverrides({ brave_api_key: apiKey.trim() });
      setStatus({ ok: true, msg: "Saved" });
      onSaved?.();
    } catch (e: any) {
      setStatus({ ok: false, msg: e?.message || "Failed to save" });
    }
  }

  function clearKey() {
    patchOverrides({ brave_api_key: "" });
    setApiKey("");
    setStatus({ ok: true, msg: "Key cleared" });
    onSaved?.();
  }

  const displayVal =
    masked && apiKey ? "•".repeat(Math.min(apiKey.length, 24)) : apiKey;

  return (
    <div className="space-y-4">
      <div className="text-sm text-gray-600">
        Enable web search via your own <b>Brave Search API</b> key. Stored in
        settings, not in local storage.
      </div>

      <div className="space-y-2">
        <label className="block text-sm">Brave API key</label>
        <div className="flex items-stretch gap-2">
          <input
            className="flex-1 border rounded px-3 py-2 text-sm"
            placeholder="X-Subscription-Token"
            value={displayVal}
            onChange={(e) => setApiKey(e.target.value)}
            onFocus={() => setMasked(false)}
            onBlur={() => setMasked(true)}
          />
          <button
            className="px-3 py-2 rounded border text-sm hover:bg-gray-50"
            onClick={() => setMasked((m) => !m)}
            title={masked ? "Show" : "Hide"}
          >
            {masked ? "Show" : "Hide"}
          </button>
          <button
            className="px-3 py-2 rounded border text-sm hover:bg-gray-50"
            onClick={clearKey}
            title="Clear key"
          >
            Clear
          </button>
          <button
            className="px-3 py-2 rounded bg-black text-white text-sm"
            onClick={save}
          >
            Save
          </button>
        </div>
        {status && (
          <div
            className={`text-xs ${status.ok ? "text-green-600" : "text-red-600"}`}
          >
            {status.msg}
          </div>
        )}
      </div>
    </div>
  );
}
