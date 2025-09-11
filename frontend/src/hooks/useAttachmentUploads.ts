import { useCallback, useMemo, useRef, useState } from "react";
import type { Attachment } from "../types/chat";
import { requestRaw } from "../services/http";

// Local UI id for keys & removal
const makeUiId = () =>
  Math.random().toString(36).slice(2) + "-" + Date.now().toString(36);

export type UIAttachment = {
  uiId: string;
  name: string;

  // UI state
  status: "uploading" | "ready" | "error";
  pct: number; // 0..100
  error?: string;

  // Optional extras
  size?: number;
  mime?: string;
  url?: string;
  serverId?: string; // if backend returns an id
};

type ReturnShape = {
  atts: UIAttachment[];
  addFiles: (files: FileList | File[]) => Promise<void>;
  removeAtt: (arg: string | UIAttachment) => void; // accepts uiId or whole object
  anyUploading: boolean;
  anyReady: boolean;
  attachmentsForPost: () => Attachment[]; // what your API expects
  reset: () => void;
};

export function useAttachmentUploads(
  sessionId?: string,
  onRefreshChats?: () => void,
): ReturnShape {
  const [atts, setAtts] = useState<UIAttachment[]>([]);
  const triedEndpoints = useRef<string[] | null>(null);

  const detectAndUpload = useCallback(
    async (file: File): Promise<UIAttachment> => {
      const endpoints = triedEndpoints.current ?? [
        "/api/rag/upload",
        "/api/rag/uploads",
        "/api/uploads",
      ];

      let lastErr: unknown = null;

      for (const ep of endpoints) {
        try {
          const fd = new FormData();
          fd.append("file", file);
          if (sessionId) fd.append("sessionId", sessionId);

          const res = await requestRaw(ep, { method: "POST", body: fd });
          const text = await res.text();
          if (!res.ok)
            throw new Error(
              `Upload failed (${res.status}) ${res.statusText} ${text || ""}`.trim(),
            );

          let data: any = {};
          try {
            data = text ? JSON.parse(text) : {};
          } catch {}

          const ui: UIAttachment = {
            uiId: makeUiId(),
            name: (data.name ?? file.name) as string,
            status: "ready",
            pct: 100,
            size: Number(data.size ?? file.size) || file.size,
            mime: (data.contentType ?? data.mime ?? file.type) as string,
            url: (data.url ?? data.location ?? undefined) as string | undefined,
            serverId: (data.id ?? data.fileId ?? data.uploadId)?.toString(),
          };

          if (!triedEndpoints.current) {
            triedEndpoints.current = [ep, ...endpoints.filter((e) => e !== ep)];
          }
          return ui;
        } catch (e) {
          lastErr = e;
        }
      }
      throw lastErr ?? new Error("No working upload endpoint found");
    },
    [sessionId],
  );

  const addFiles = useCallback(
    async (files: FileList | File[]) => {
      const arr = Array.from(files);
      if (arr.length === 0) return;

      // optimistic rows
      const optimistic: UIAttachment[] = arr.map((f) => ({
        uiId: makeUiId(),
        name: f.name,
        status: "uploading",
        pct: 0,
        size: f.size,
        mime: f.type,
      }));
      setAtts((cur) => [...cur, ...optimistic]);

      await Promise.all(
        arr.map(async (file, i) => {
          const tempUiId = optimistic[i].uiId;
          try {
            const finalUi: UIAttachment = sessionId
              ? await detectAndUpload(file)
              : {
                  uiId: makeUiId(),
                  name: file.name,
                  status: "ready",
                  pct: 100,
                  size: file.size,
                  mime: file.type,
                };

            setAtts((cur) =>
              cur.map((a) => (a.uiId === tempUiId ? finalUi : a)),
            );
          } catch (e: any) {
            setAtts((cur) =>
              cur.map((a) =>
                a.uiId === tempUiId
                  ? {
                      ...a,
                      status: "error",
                      pct: 0,
                      error: e?.message ?? "Upload failed.",
                    }
                  : a,
              ),
            );
          }
        }),
      );

      onRefreshChats?.();
    },
    [detectAndUpload, onRefreshChats, sessionId],
  );

  const removeAtt = useCallback((arg: string | UIAttachment) => {
    const uiId = typeof arg === "string" ? arg : arg.uiId;
    setAtts((cur) => cur.filter((a) => a.uiId !== uiId));
  }, []);

  const anyUploading = useMemo(
    () => atts.some((a) => a.status === "uploading"),
    [atts],
  );
  const anyReady = useMemo(
    () => atts.some((a) => a.status === "ready"),
    [atts],
  );

  const attachmentsForPost = useCallback((): Attachment[] => {
    return atts
      .filter((a) => a.status === "ready")
      .map<Attachment>((a) => {
        const out = { name: a.name } as Attachment;
        // If your Attachment type supports these, you can add them:
        // (out as any).url = a.url;
        // (out as any).contentType = a.mime;
        // (out as any).bytes = a.size;
        // (out as any).id = a.serverId;
        return out;
      });
  }, [atts]);

  const reset = useCallback(() => setAtts([]), []);

  return {
    atts,
    addFiles,
    removeAtt,
    anyUploading,
    anyReady,
    attachmentsForPost,
    reset,
  };
}

// Back-compat alias if you want to import as Att
export type Att = UIAttachment;
