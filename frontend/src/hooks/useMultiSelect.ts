// frontend/src/file_read/hooks/useMultiSelect.ts
import { useEffect, useMemo, useState } from "react";

export function useMultiSelect(allIds: string[]) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // keep selection pruned when the list of ids changes
  useEffect(() => {
    setSelected((prev) => {
      const next = new Set([...prev].filter((id) => allIds.includes(id)));
      // only update if it actually changed
      return next.size === prev.size ? prev : next;
    });
  }, [allIds]);

  const allSelected = useMemo(
    () => selected.size > 0 && selected.size === allIds.length,
    [selected, allIds.length],
  );

  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected((prev) =>
      prev.size === allIds.length ? new Set() : new Set(allIds),
    );
  };

  return { selected, setSelected, allSelected, toggleOne, toggleAll };
}
