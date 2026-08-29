"use client";

import { useTranslations } from "next-intl";

/**
 * The first thing a keyboard reaches on every page.
 *
 * Off-screen until focused, then visible. Without it, someone navigating by keyboard tabs through
 * the whole sidebar on every single page before reaching the content — which is not a small
 * inconvenience, it is the difference between a usable product and an unusable one.
 */
export function SkipLink() {
  const t = useTranslations("a11y");

  return (
    <a className="ub-skip-link" href="#main">
      {t("skipToContent")}
    </a>
  );
}
