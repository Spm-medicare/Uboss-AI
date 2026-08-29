"use client";

/**
 * Light, dark, or follow the operating system.
 *
 * The choice is stored in `localStorage` because it is a per-browser preference, not account
 * data: the same person may want dark on a laptop at night and light on a shared screen. It is
 * applied before first paint by the bootstrap script in `theme-script.ts`, so the page never
 * flashes the wrong theme.
 *
 * The theme lives on the document, not in React state — the bootstrap script sets it before
 * React exists, another tab can change it, and the operating system can change underneath both.
 * React subscribes to it as an external system (`useTheme`) rather than trying to own it.
 */

import { useSyncExternalStore } from "react";

import {
  THEME_EVENT,
  THEME_STORAGE_KEY,
  type ResolvedTheme,
  type ThemeChoice,
} from "./theme-script";

export type { ResolvedTheme, ThemeChoice };

function readStoredChoice(): ThemeChoice {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    /* Storage unavailable. Following the system is the safe answer. */
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

export interface ThemeState {
  /** What the person asked for. */
  choice: ThemeChoice;
  /** What is actually on screen once "system" is resolved. */
  resolved: ResolvedTheme;
}

//  The snapshot is cached so that `useSyncExternalStore` gets the *same object* back on every
//  render until something really changes. Returning a fresh object each time would make React
//  believe the store changed on every render and loop forever.
let snapshot: ThemeState = { choice: "system", resolved: "light" };

const SERVER_SNAPSHOT: ThemeState = { choice: "system", resolved: "light" };

function computeSnapshot(): ThemeState {
  const choice = readStoredChoice();
  const resolved: ResolvedTheme =
    choice === "system" ? (systemPrefersDark() ? "dark" : "light") : choice;
  if (choice !== snapshot.choice || resolved !== snapshot.resolved) {
    snapshot = { choice, resolved };
  }
  return snapshot;
}

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const handle = () => {
    computeSnapshot();
    onChange();
  };
  media.addEventListener("change", handle);
  // `storage` fires in the *other* tabs, so a change made in one window follows the person into
  // the next. The custom event covers this tab, where `storage` deliberately does not fire.
  window.addEventListener("storage", handle);
  window.addEventListener(THEME_EVENT, handle);
  return () => {
    media.removeEventListener("change", handle);
    window.removeEventListener("storage", handle);
    window.removeEventListener(THEME_EVENT, handle);
  };
}

/**
 * The current theme, kept in step with storage, this tab and the operating system.
 *
 * On the server it reports light — the bootstrap script has already painted the real theme by
 * the time the browser reaches this, so the first client snapshot corrects it without a flash.
 */
export function useTheme(): ThemeState {
  return useSyncExternalStore(subscribe, computeSnapshot, () => SERVER_SNAPSHOT);
}

/** Apply a choice immediately, remember it, and tell every subscriber. */
export function applyThemeChoice(choice: ThemeChoice): void {
  const dark = choice === "dark" || (choice === "system" && systemPrefersDark());

  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";

  try {
    if (choice === "system") localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    /* The theme still changed for this page; it just will not be remembered. */
  }

  computeSnapshot();
  window.dispatchEvent(new Event(THEME_EVENT));
}
