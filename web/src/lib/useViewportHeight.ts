import { useEffect, useState } from "react";

/** The window's inner height, updated on resize. */
export function useViewportHeight(fallback = 900): number {
  const [height, setHeight] = useState(() => (typeof window === "undefined" ? fallback : window.innerHeight));
  useEffect(() => {
    const update = () => setHeight(window.innerHeight);
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return height;
}
