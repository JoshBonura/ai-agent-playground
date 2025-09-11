import { useState } from "react";

type BySession<T> = Record<string, T>;

export function useRunState() {
  const [loadingBy, setLoadingBy] = useState<BySession<boolean>>({});
  const [queuedBy, setQueuedBy] = useState<BySession<boolean>>({});

  const setBool =
    (setter: React.Dispatch<React.SetStateAction<BySession<boolean>>>) =>
    (sid: string, v: boolean) =>
      setter((prev) => (prev[sid] === v ? prev : { ...prev, [sid]: v }));

  return {
    loadingBy,
    queuedBy,
    setLoadingFor: setBool(setLoadingBy),
    setQueuedFor: setBool(setQueuedBy),
  };
}
