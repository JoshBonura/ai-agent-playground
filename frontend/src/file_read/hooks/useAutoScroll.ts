// frontend/src/file_read/hooks/useAutoScroll.ts
import { useEffect } from "react";

type AnyRef<T extends HTMLElement> = { current: T | null };

/**
 * Auto-scrolls to bottom when the user is already near the bottom.
 * Supports BOTH:
 *   1) useAutoScroll(ref, [dep1, dep2],)          // old style
 *   2) useAutoScroll(ref, thresholdPx, dep1, dep2) // new style with threshold
 */
export function useAutoScroll<T extends HTMLElement>(
  ref: AnyRef<T>,
  depsOrThreshold: any[] | number = [],
  ...restDeps: any[]
) {
  const thresholdPx =
    typeof depsOrThreshold === "number" ? depsOrThreshold : 24;
  const deps = Array.isArray(depsOrThreshold) ? depsOrThreshold : restDeps;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const atBottom = distanceFromBottom <= thresholdPx;

    if (atBottom) {
      // wait a tick so layout paints, then scroll
      requestAnimationFrame(() => {
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      });
    }
    // include threshold so changing it retriggers
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [thresholdPx, ...deps]);
}
