import { useCallback, useEffect, useRef, useState } from "react";

type State<T> = { data: T | undefined; error: Error | null; loading: boolean };

/** Load data on mount and on demand. Ignores results from superseded requests. */
export function useResource<T>(load: () => Promise<T>) {
  const [state, setState] = useState<State<T>>({ data: undefined, error: null, loading: true });
  const generation = useRef(0);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  const reload = useCallback(async () => {
    const current = ++generation.current;
    setState((previous) => ({ ...previous, loading: true, error: null }));
    try {
      const data = await loadRef.current();
      if (current === generation.current) setState({ data, error: null, loading: false });
    } catch (error) {
      if (current === generation.current)
        setState((previous) => ({ ...previous, error: error as Error, loading: false }));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { ...state, reload };
}
