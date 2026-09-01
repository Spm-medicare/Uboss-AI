"use client";

import { useTranslations } from "next-intl";

import type { CurrentUser } from "@/lib/api/contract";
import { cn } from "@/lib/cn";
import { CATEGORIES, type SettingsCategory } from "@/ui/settings/catalogue";
import {
  AppearanceSection,
  NotBuiltSection,
  NotificationsSection,
  ProfileSection,
  SecuritySection,
} from "@/ui/settings/sections";

/**
 * §13's Settings, as a two-pane panel: *"category navigation left and focused content right."*
 *
 * One component, two containers. It is the body of the overlay the header and the sidebar open, and
 * the body of `/settings` for anybody who arrives by link — because the same screen reached two ways
 * has to be the same screen, and two copies would drift the way the three copies this codebase has
 * already had to merge did.
 *
 * Which category is open is a prop, so each container decides where that lives: the overlay keeps it
 * in component state (it is a panel over your work, and closing it should not leave anything in the
 * URL), the page keeps it in a query parameter (a link to somebody's security settings is useful).
 */
export function SettingsPanel({
  user,
  chosen,
  onChoose,
}: {
  user: CurrentUser;
  chosen: SettingsCategory;
  onChoose: (category: SettingsCategory) => void;
}) {
  const t = useTranslations("settings");

  return (
    <div className="grid gap-5 lg:grid-cols-[15rem_minmax(0,1fr)]">
      <nav aria-label={t("categories")} className="space-y-4 lg:max-h-[70vh] lg:overflow-y-auto">
        {(["personal", "workspace"] as const).map((group) => (
          <div key={group}>
            <h2 className="mb-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t(`group.${group}`)}
            </h2>
            <ul className="space-y-0.5">
              {CATEGORIES.filter((category) => category.group === group).map((category) => (
                <li key={category.id}>
                  <button
                    type="button"
                    aria-current={category.id === chosen.id ? "page" : undefined}
                    onClick={() => onChoose(category)}
                    className={cn(
                      "flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5",
                      "text-left text-sm transition-colors duration-150 motion-reduce:transition-none",
                      "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                      category.id === chosen.id
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-accent",
                    )}
                  >
                    <span className="min-w-0 truncate">
                      {t(`category.${category.id}` as "category.profile")}
                    </span>
                    {/*  Labelled, not hidden. A category with no screen behind it says so here and
                        again when it is opened. */}
                    {!category.built ? (
                      <span
                        className={cn(
                          "shrink-0 rounded px-1.5 py-0.5 text-[0.625rem] font-medium uppercase",
                          category.id === chosen.id
                            ? "bg-primary-foreground/20"
                            : "bg-muted text-muted-foreground",
                        )}
                      >
                        {t("soon")}
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="min-w-0 lg:max-h-[70vh] lg:overflow-y-auto lg:pr-1">
        <Section category={chosen} user={user} />
      </div>
    </div>
  );
}

function Section({ category, user }: { category: SettingsCategory; user: CurrentUser }) {
  if (!category.built) {
    return <NotBuiltSection id={category.id} gate={category.gate ?? "Gate 8"} />;
  }

  switch (category.id) {
    case "profile":
      return <ProfileSection user={user} />;
    case "appearance":
      return <AppearanceSection />;
    case "notifications":
      return <NotificationsSection user={user} />;
    case "security":
      return <SecuritySection user={user} />;
    default:
      //  Unreachable while `built` and this switch agree. If they ever part company, the honest
      //  answer is the not-built panel rather than a blank pane.
      return <NotBuiltSection id={category.id} gate={category.gate ?? "Gate 8"} />;
  }
}
