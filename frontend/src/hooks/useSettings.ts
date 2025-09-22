import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getEffective,
  getOverrides,
  getDefaults,
  patchOverrides,
  putOverrides,
} from "../data/settingsApi";

type State = {
  loading: boolean;
  loadingSoft: boolean; // ← soft refresh flag (no header flash)
  error: string | null;
  effective: any | null;
  overrides: any | null;
  defaults: any | null;
};

export function useSettings(sessionId?: string) {
  const [state, setState] = useState<State>({
    loading: false,
    loadingSoft: false,
    error: null,
    effective: null,
    overrides: null,
    defaults: null,
  });

  // Delayed hard loader + soft mode
  const load = useCallback(
    async (opts?: { soft?: boolean }) => {
      const isSoft = !!opts?.soft;
      let timer: number | null = null;

      // mark soft/hard intent immediately
      setState((s) => ({ ...s, error: null, loadingSoft: isSoft }));

      // only show the big loader if it takes longer than 150ms (and not soft)
      if (!isSoft) {
        timer = window.setTimeout(() => {
          setState((s) => ({ ...s, loading: true }));
        }, 150);
      }

      try {
        console.log("[useSettings] load()", { soft: isSoft });
        const [effective, overrides, defaults] = await Promise.all([
          getEffective(sessionId),
          getOverrides(),
          getDefaults(),
        ]);

        if (timer) window.clearTimeout(timer);
        setState({
          loading: false,
          loadingSoft: false,
          error: null,
          effective,
          overrides,
          defaults,
        });
      } catch (e: any) {
        if (timer) window.clearTimeout(timer);
        setState((s) => ({
          ...s,
          loading: false,
          loadingSoft: false,
          error: e?.message || "Failed to load settings",
        }));
      }
    },
    [sessionId],
  );

  // Initial full (hard) load
  useEffect(() => {
    void load();
  }, [load]);

  // Save then do a soft refresh (no header flash)
  const saveOverrides = useCallback(
    async (data: Record<string, any>, method: "patch" | "put" = "patch") => {
      console.time("[useSettings] saveOverrides");
      if (method === "put") await putOverrides(data);
      else await patchOverrides(data);
      console.timeEnd("[useSettings] saveOverrides");
      await load({ soft: true });
    },
    [load],
  );

  return useMemo(
    () => ({ ...state, reload: load, saveOverrides }),
    [state, load, saveOverrides],
  );
}
