/**
 * Which languages exist, and which one is the fallback.
 *
 * PLAN §21.1 and `DR-002`: English at launch, a Hindi pack when approved. The framework is here
 * from the first screen — retrofitting it across five screens is an afternoon, across forty it is
 * a week, and the forty are coming.
 *
 * `hi` is **not** listed yet. Adding it before the translations exist would show a person a
 * half-translated interface, which is worse than an English one: they cannot tell whether a
 * missing word is a bug or a feature they do not have.
 */

export const LOCALES = ["en"] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}
