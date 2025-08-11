import { useEffect } from "react";

type AnyRef<T extends HTMLElement> = { current: T | null };

export function useAutoScroll<T extends HTMLElement>(ref: AnyRef<T>, deps: any[] = []) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    console.log("useAutoScroll triggered");

    const isAtBottom = el.scrollHeight - el.scrollTop === el.clientHeight;

    // Log the scroll position and whether we're at the bottom
    console.log({
      scrollHeight: el.scrollHeight,
      scrollTop: el.scrollTop,
      clientHeight: el.clientHeight,
      isAtBottom,
    });

    // Scroll to the bottom if the user is already near the bottom
    if (isAtBottom) {
      console.log("Scrolling to bottom...");
      el.scrollTo({
        top: el.scrollHeight,  // Scroll to the bottom
        behavior: "smooth",    // Smooth scroll
      });
    }
  }, [deps]);  // Trigger the effect when dependencies change (e.g., messages or loading)
}
