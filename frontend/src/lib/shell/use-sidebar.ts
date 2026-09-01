"use client";

/**
 * Expanded or collapsed, and remembered.
 *
 * **Collapsed is the default.** Somebody who has never touched it gets the icon rail; the
 * remembered preference takes over from their first click.
 *
 * PLAN §3: *"Expanded and collapsed modes with remembered user preference."* Remembered is the
 * part that is easy to get wrong. A person who collapses the sidebar has said something about how
 * they want to work; giving it back to them expanded on every visit ignores it.
 *
 * Stored in `localStorage` rather than on the server, deliberately. It is a per-device preference:
 * the same person wants it collapsed on a laptop and expanded on a wide monitor, and a
 * server-stored value would fight them across devices. Nothing about it is worth a round trip.
 *
 * Read through `useSyncExternalStore` rather than copied into state inside an effect. Storage is
 * an external store, and this is the API for reading one: React uses the server snapshot while
 * hydrating — so the markup matches and the tree is not thrown away — then re-reads on the
 * client. Copying it in an effect would render twice and, because the intermediate value is the
 * *wrong* one, would flash the sidebar open before closing it.
 *
 * The subscription also means two open tabs agree. `storage` fires in the other tabs; the local
 * listener set covers this one, which `storage` deliberately does not.
 */

import { useCallback, useSyncExternalStore } from "react";

const COLLAPSED_KEY = "uboss.sidebar.collapsed";

const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function read(key: string, fallback: boolean): boolean {
  try {
    const stored = window.localStorage.getItem(key);
    return stored === null ? fallback : stored === "true";
  } catch {
    //  Storage can be unavailable — a private window, or a browser configured to refuse it. The
    //  default is usable, and a preference is not worth an error.
    return fallback;
  }
}

function write(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, String(value));
  } catch {
    //  Not remembered. The toggle still works for this session, which is the part that matters.
  }
  for (const listener of listeners) listener();
}

/**
 * Put the sidebar back to collapsed.
 *
 * Called on a fresh sign-in. **This deliberately overrides the remembered preference**, which §3
 * asks for and which the toggle still writes: the instruction is that every login starts with the
 * rail, so the preference lasts the session rather than the device. Somebody who expands it keeps
 * it expanded until they sign out again.
 */
export function collapseSidebar(): void {
  write(COLLAPSED_KEY, true);
}

export interface SidebarState {
  collapsed: boolean;
  toggle: () => void;
  /**
   * False until the stored preference has been read. Used to suppress the width transition on the
   * first paint, so a person who chose collapsed does not watch it slide shut on every load.
   */
  ready: boolean;
}

//  **Collapsed until somebody says otherwise.** The rail is the default: a person arriving at
//  work wants the screen, and the icons plus their tooltips are enough to navigate by. §3's
//  "remembered user preference" still wins the moment they express one — the fallback only
//  answers for somebody who never has.
//
//  The server snapshot below has to match this, or React hydrates against markup for the other
//  state and throws the tree away — which is visible as the sidebar flicking open and shut.
const COLLAPSED_BY_DEFAULT = true;

export function useSidebar(): SidebarState {
  const collapsed = useSyncExternalStore(
    subscribe,
    () => read(COLLAPSED_KEY, COLLAPSED_BY_DEFAULT),
    () => COLLAPSED_BY_DEFAULT,
  );
  const ready = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );

  const toggle = useCallback(() => {
    write(COLLAPSED_KEY, !read(COLLAPSED_KEY, COLLAPSED_BY_DEFAULT));
  }, []);

  return { collapsed, toggle, ready };
}
