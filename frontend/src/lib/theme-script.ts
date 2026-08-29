/**
 * The theme bootstrap, kept free of React so a Server Component can import it.
 *
 * `layout.tsx` renders on the server and needs the script string; the hook that reads the theme
 * needs React and therefore a client boundary. Splitting them here means the layout does not
 * have to become a Client Component just to put one `<script>` in the head.
 */

export type ThemeChoice = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "uboss.theme";

/** Dispatched on `window` when this tab changes the theme, so subscribers in this tab hear it. */
export const THEME_EVENT = "uboss:theme";

/**
 * Runs in the document head, before React and before the first paint.
 *
 * Written as a string rather than an imported function because it has to execute synchronously
 * during parsing — anything that waits for hydration is already too late to prevent the flash.
 * Every access is inside a try/catch: a private window, or a browser set to block site data,
 * throws on `localStorage` rather than returning null, and a theme preference is never worth a
 * blank page.
 */
export const THEME_BOOTSTRAP_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem("${THEME_STORAGE_KEY}");
    var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    var dark = stored === "dark" || (stored !== "light" && prefersDark);
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
  } catch (e) {
    /* No stored preference is readable. The stylesheet's light defaults apply. */
  }
})();
`;
