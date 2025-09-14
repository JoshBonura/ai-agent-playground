import { useEffect, useState } from "react";
import { getModelHealth } from "../api/models";

export function useModelHealth(pollMs = 5000) {
  const [loaded, setLoaded] = useState<boolean>(true); // default optimistic
  useEffect(() => {
    let alive = true, t: any;
    const tick = async () => {
      try { const h = await getModelHealth(); if (alive) setLoaded(!!h.loaded); }
      catch { if (alive) setLoaded(false); }
      t = setTimeout(tick, pollMs);
    };
    tick();
    return () => { alive = false; clearTimeout(t); };
  }, [pollMs]);
  return loaded;
}
