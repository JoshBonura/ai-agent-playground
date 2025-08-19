// frontend/src/file_read/pages/useInitialLoad.ts
import { useEffect } from "react";
import { listChatsPage } from "../data/chatApi";

export function useInitialLoad(
  pageSize: number,
  onPick: (id: string) => Promise<void>,
  keyName = "lastSessionId"
) {
  useEffect(() => {
    (async () => {
      try {
        const ceil = new Date().toISOString();
        const page = await listChatsPage(0, pageSize, ceil);
        const saved = localStorage.getItem(keyName) || "";
        const targetId =
          (saved && page.content.find(c => c.sessionId === saved)?.sessionId) ||
          page.content[0]?.sessionId || "";
        if (targetId) {
          await onPick(targetId);
          localStorage.setItem(keyName, targetId);
        }
      } catch {}
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
