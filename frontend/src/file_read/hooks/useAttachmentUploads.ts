import { useState } from "react";
import { uploadRagWithProgress, deleteUploadHard } from "../data/ragApi";

export type Att = {
  id: string;
  name: string;
  pct: number;
  status: "uploading" | "ready" | "error";
  abort?: AbortController;
};

export function useAttachmentUploads(sessionId?: string, onRefreshChats?: () => void) {
  const [atts, setAtts] = useState<Att[]>([]);

  const anyUploading = atts.some(a => a.status === "uploading");
  const anyReady = atts.some(a => a.status === "ready");

  async function addFiles(files: FileList | File[]) {
    if (!files || !sessionId) return;
    const picked = Array.from(files);
    const news: Att[] = picked.map((f, i) => ({
      id: `${Date.now()}-${i}-${f.name}`,
      name: f.name,
      pct: 0,
      status: "uploading",
      abort: new AbortController(),
    }));
    setAtts(prev => [...prev, ...news]);

    news.forEach((att, idx) => {
      const f = picked[idx];
      uploadRagWithProgress(
        f,
        sessionId,
        (pct) => setAtts(prev => prev.map(a => a.id === att.id ? { ...a, pct } : a)),
        att.abort?.signal
      )
        .then(() => {
          setAtts(prev => prev.map(a => a.id === att.id ? { ...a, pct: 100, status: "ready", abort: undefined } : a));
          onRefreshChats?.();
        })
        .catch(() => {
          setAtts(prev => prev.map(a => a.id === att.id ? { ...a, status: "error", abort: undefined } : a));
        });
    });
  }

  async function removeAtt(att: Att) {
    if (att.status === "uploading" && att.abort) {
      try { att.abort.abort(); } catch {}
    }
    if (sessionId) {
      try { await deleteUploadHard(att.name, sessionId); } catch {}
    }
    setAtts(prev => prev.filter(a => a.id !== att.id));
    onRefreshChats?.();
  }

  function attachmentsForPost(): Array<{ name: string; source: string; sessionId: string }> {
    if (!sessionId) return [];
    return atts
      .filter(a => a.status === "ready")
      .map(a => ({ name: a.name, source: a.name, sessionId }));
  }

  function reset() {
    setAtts([]);
  }

  return { atts, addFiles, removeAtt, anyUploading, anyReady, attachmentsForPost, reset };
}
