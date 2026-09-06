import { useCallback, useEffect, useState } from "react";

/**
 * Minimal hash router.
 *
 * Deliberately not react-router: the app needs five sibling views and nothing
 * else — no nested routes, no loaders, no params — so a hash fragment carries
 * everything required without adding a dependency.
 *
 * Hash routing also means no server rewrite rules, so a deep link keeps working
 * when the built app is served as static files.
 */
export function useHashRoute<T extends string>(
  routes: readonly T[],
  fallback: T
): readonly [T, (next: T) => void] {
  const read = useCallback((): T => {
    const raw = window.location.hash.replace(/^#\/?/, "").split("?")[0];
    return (routes as readonly string[]).includes(raw) ? (raw as T) : fallback;
  }, [routes, fallback]);

  const [route, setRoute] = useState<T>(read);

  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener("hashchange", onChange);
    // An unknown or empty hash should settle on a real route so the address bar
    // always reflects what is on screen.
    if (window.location.hash.replace(/^#\/?/, "") !== route) {
      window.history.replaceState(null, "", `#/${route}`);
    }
    return () => window.removeEventListener("hashchange", onChange);
  }, [read, route]);

  const navigate = useCallback((next: T) => {
    if (next === read()) return;
    window.location.hash = `/${next}`;
    // Land at the top of the new view rather than keeping the old scroll offset.
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [read]);

  return [route, navigate] as const;
}
