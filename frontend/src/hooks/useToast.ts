import { useState } from "react";

export function useToast() {
  const [toast, setToast] = useState<string | null>(null);
  function show(msg: string, ms = 1800) {
    setToast(msg);
    window.clearTimeout((show as any)._t);
    (show as any)._t = window.setTimeout(() => setToast(null), ms);
  }
  return { toast, show };
}
