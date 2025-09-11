import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getEffective,
  getOverrides,
  getDefaults,
  getAdaptive,
  patchOverrides,
  putOverrides,
  recomputeAdaptive,
} from "../data/settingsApi";

type State = {
  loading: boolean;
  error: string | null;
  effective: any | null;
  overrides: any | null;
  defaults: any | null;
  adaptive: any | null;
};

export function useSettings(sessionId?: string) {
  const [state, setState] = useState<State>({
    loading: false,
    error: null,
    effective: null,
    overrides: null,
    defaults: null,
    adaptive: null,
  });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const [effective, overrides, defaults, adaptive] = await Promise.all([
        getEffective(sessionId),
        getOverrides(),
        getDefaults(),
        getAdaptive(),
      ]);
      setState({
        loading: false,
        error: null,
        effective,
        overrides,
        defaults,
        adaptive,
      });
    } catch (e: any) {
      setState((s) => ({
        ...s,
        loading: false,
        error: e?.message || "Failed to load settings",
      }));
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const saveOverrides = useCallback(
    async (data: Record<string, any>, method: "patch" | "put" = "patch") => {
      if (method === "put") await putOverrides(data);
      else await patchOverrides(data);
      await load();
    },
    [load],
  );

  const runAdaptive = useCallback(async () => {
    await recomputeAdaptive(sessionId);
    await load();
  }, [load, sessionId]);

  return useMemo(
    () => ({
      ...state,
      reload: load,
      saveOverrides,
      runAdaptive,
    }),
    [state, load, saveOverrides, runAdaptive],
  );
}
