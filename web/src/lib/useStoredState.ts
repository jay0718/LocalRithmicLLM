import { useEffect, useState } from "react";

/**
 * State kept in this browser under ``key``, so a choice survives reloads. Falls back to
 * ``initial`` when storage is empty, unreadable or blocked (private windows).
 */
export function useStoredState<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Without storage the choice lasts for this visit.
    }
  }, [key, value]);
  return [value, setValue];
}
