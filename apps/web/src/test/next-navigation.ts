/**
 * In-memory stand-in for `next/navigation` (aliased in vitest.config.ts).
 * Components only use `usePathname` and `useRouter`, so a tiny router that
 * holds one pathname is enough to exercise real route-driven behaviour.
 */
import { useSyncExternalStore } from "react";

let current = "/";
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function __setPath(path: string): void {
  current = path;
  listeners.forEach((listener) => listener());
}

export function __getPath(): string {
  return current;
}

export function usePathname(): string {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => current,
  );
}

const router = {
  push: (path: string) => __setPath(path),
  replace: (path: string) => __setPath(path),
  back: () => {},
  forward: () => {},
  refresh: () => {},
  prefetch: () => {},
};

export function useRouter() {
  return router;
}
