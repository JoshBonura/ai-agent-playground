import { useEffect } from "react";

export function useLockBodyScroll(lock: boolean) {
  useEffect(() => {
    const { overflow } = document.body.style;
    if (lock) document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = overflow; };
  }, [lock]);
}
