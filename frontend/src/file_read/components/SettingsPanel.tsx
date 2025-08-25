import { useEffect, useMemo, useState } from "react";
import { useSettings } from "../hooks/useSettings";

export default function SettingsPanel({ sessionId, onClose }: { sessionId?: string; onClose?: () => void }) {
  const { loading, error, effective, overrides, defaults, adaptive, saveOverrides, runAdaptive, reload } =
    useSettings(sessionId);

  const [tab, setTab] = useState<"effective"|"overrides"|"adaptive"|"defaults">("effective");
  const [draft, setDraft] = useState(() => JSON.stringify(overrides ?? {}, null, 2));
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  useEffect(() => { setDraft(JSON.stringify(overrides ?? {}, null, 2)); }, [overrides]);

  const view = useMemo(() => {
    switch (tab) {
      case "effective": return effective;
      case "adaptive":  return adaptive;
      case "defaults":  return defaults;
      case "overrides": return null;
    }
  }, [tab, effective, adaptive, defaults]);

  async function onSave(method: "patch" | "put") {
    setSaveErr(null); setSaveBusy(true);
    try {
      const parsed = draft.trim() ? JSON.parse(draft) : {};
      await saveOverrides(parsed, method);
    } catch (e: any) {
      setSaveErr(e?.message || "Invalid JSON or save failed");
    } finally {
      setSaveBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-3">
      <div className="w-full max-w-4xl rounded-2xl bg-white shadow-xl border">
        {/* header */}
        <div className="px-4 py-3 border-b flex items-center gap-2">
          <div className="font-semibold">Settings</div>
          <div className="ml-auto flex items-center gap-2">
            <button
              className="text-xs px-3 py-1.5 rounded border hover:bg-gray-50"
              onClick={() => runAdaptive()}
              title="Recompute adaptive with current context"
            >
              Recompute Adaptive
            </button>
            <button
              className="text-xs px-3 py-1.5 rounded border hover:bg-gray-50"
              onClick={() => reload()}
              title="Reload"
            >
              Reload
            </button>
            <button
              className="text-xs px-3 py-1.5 rounded border hover:bg-gray-50"
              onClick={onClose}
              title="Close"
            >
              Close
            </button>
          </div>
        </div>

        {/* tabs */}
        <div className="px-4 py-2 border-b">
          {(["effective","overrides","adaptive","defaults"] as const).map(key => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`text-xs mr-2 px-3 py-1.5 rounded ${tab===key ? "bg-black text-white" : "border hover:bg-gray-50"}`}
            >
              {key}
            </button>
          ))}
        </div>

        {/* body */}
        <div className="p-4">
          {loading && <div className="text-sm text-gray-500">Loading…</div>}
          {error && <div className="text-sm text-red-600">{error}</div>}

          {tab !== "overrides" && (
            <pre className="text-xs bg-gray-50 border rounded p-3 overflow-auto max-h-[60vh]">
              {JSON.stringify(view ?? {}, null, 2)}
            </pre>
          )}

          {tab === "overrides" && (
            <div className="space-y-2">
              <div className="text-xs text-gray-600">
                Edit <code>user_overrides</code> JSON. Use <b>Patch</b> to merge or <b>Replace</b> to overwrite.
              </div>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className="w-full h-[50vh] border rounded p-2 font-mono text-xs"
                spellCheck={false}
              />
              <div className="flex items-center gap-2">
                <button
                  className={`text-xs px-3 py-1.5 rounded ${saveBusy ? "opacity-60 cursor-not-allowed" : "bg-black text-white"}`}
                  disabled={saveBusy}
                  onClick={() => onSave("patch")}
                  title="Deep-merge with existing overrides"
                >
                  Save (Patch)
                </button>
                <button
                  className={`text-xs px-3 py-1.5 rounded border ${saveBusy ? "opacity-60 cursor-not-allowed" : "hover:bg-gray-50"}`}
                  disabled={saveBusy}
                  onClick={() => onSave("put")}
                  title="Replace overrides entirely"
                >
                  Save (Replace)
                </button>
                {saveErr && <div className="text-xs text-red-600 ml-2">{saveErr}</div>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
