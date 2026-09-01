"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { CurrentUser, NotificationPreference } from "@/lib/api/contract";
import { fetchSessions, revokeSession, updateProfile } from "@/lib/api/auth";
import {
  fetchNotificationPreferences,
  fetchNotificationSettings,
  saveNotificationPreference,
  saveNotificationSettings,
} from "@/lib/api/notifications";
import { useSignOut } from "@/lib/auth/use-session";
import { cn } from "@/lib/cn";
import { contextFor, formatDateTimeWithZone } from "@/lib/format";
import { applyThemeChoice, useTheme } from "@/lib/theme";
import { Alert, Badge, Button, Field, Input, QueryStates } from "@/ui";

/** A titled block, so every section reads the same way. */
export function Panel({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <header className="space-y-1">
        <h2 className="text-sm font-semibold">{title}</h2>
        {description ? (
          <p className="text-sm text-muted-foreground">{description}</p>
        ) : null}
      </header>
      {children}
    </section>
  );
}

/**
 * §13's *"Profile and timezone/locale"*.
 *
 * Three fields a person owns. Not their email — that is how they sign in — and not their roles,
 * which are somebody else's decision by definition. Both are shown, and shown as facts rather than
 * as disabled inputs: a greyed-out box invites a person to look for the way to enable it.
 *
 * **The timezone is why this section exists.** `CurrentUser.timezone` is what every screen in the
 * product formats instants with, and until `PATCH /auth/me` there was nothing that wrote it — so
 * somebody working in Dubai read a workspace of Kolkata times.
 */
export function ProfileSection({ user }: { user: CurrentUser }) {
  const t = useTranslations("settings");
  const queryClient = useQueryClient();
  const [name, setName] = useState(user.display_name);
  const [title, setTitle] = useState(user.job_title ?? "");
  const [zone, setZone] = useState(user.timezone);

  const save = useMutation({
    mutationFn: () =>
      updateProfile(
        {
          display_name: name.trim(),
          job_title: title.trim() || null,
          timezone: zone,
        },
        //  Where it is coming *from*, so the key names the transition. See `updateProfile`: keyed
        //  on the destination alone, changing back and forth replays the first answer for ever.
        {
          display_name: user.display_name,
          job_title: user.job_title ?? null,
          timezone: user.timezone,
        },
      ),
    onSuccess: () => {
      //  Every screen formats times from this, so the whole app is stale until it is refetched.
      void queryClient.invalidateQueries({ queryKey: ["session"] });
    },
  });

  //  The browser's own list, which is the same IANA database the backend validates against. A
  //  hand-kept list of "common" zones is a list that is wrong for somebody.
  const zones =
    typeof Intl.supportedValuesOf === "function"
      ? Intl.supportedValuesOf("timeZone")
      : [user.timezone];

  const dirty =
    name.trim() !== user.display_name ||
    (title.trim() || null) !== (user.job_title ?? null) ||
    zone !== user.timezone;

  return (
    <Panel title={t("profile.title")} description={t("profile.description")}>
      <Field label={t("profile.name")} htmlFor="profile-name" required>
        {(field) => (
          <Input {...field} value={name} onChange={(event) => setName(event.target.value)} />
        )}
      </Field>

      <Field label={t("profile.jobTitle")} htmlFor="profile-title">
        {(field) => (
          <Input {...field} value={title} onChange={(event) => setTitle(event.target.value)} />
        )}
      </Field>

      <Field
        label={t("profile.timezone")}
        hint={t("profile.timezoneHint")}
        htmlFor="profile-timezone"
      >
        {(field) => (
          <select
            {...field}
            value={zone}
            onChange={(event) => setZone(event.target.value)}
            className={cn(
              "h-9 w-full rounded-md border border-border bg-card px-3 text-sm",
              "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ub-focus)]",
            )}
          >
            {zones.map((name_) => (
              <option key={name_} value={name_}>
                {name_}
              </option>
            ))}
          </select>
        )}
      </Field>

      {/*  Facts, not disabled inputs. Each says who decides it instead of implying nobody does. */}
      <dl className="grid gap-2 border-t border-border pt-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted-foreground">{t("profile.email")}</dt>
          <dd>{user.email}</dd>
          <dd className="text-xs text-muted-foreground">{t("profile.emailWhy")}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">{t("profile.roles")}</dt>
          <dd className="flex flex-wrap gap-1">
            {user.roles.length > 0 ? (
              user.roles.map((role) => (
                <Badge key={role} tone="neutral">
                  {role}
                </Badge>
              ))
            ) : (
              <span className="text-muted-foreground">{t("profile.noRoles")}</span>
            )}
          </dd>
          <dd className="text-xs text-muted-foreground">{t("profile.rolesWhy")}</dd>
        </div>
      </dl>

      {save.isError ? (
        <Alert tone="danger" title={t("notSaved")}>
          {(save.error as Error).message}
        </Alert>
      ) : null}
      {save.isSuccess && !dirty ? (
        <Alert tone="success" title={t("saved")}>
          {t("profile.savedBody")}
        </Alert>
      ) : null}

      <Button
        variant="primary"
        size="sm"
        busy={save.isPending}
        disabled={!dirty || !name.trim()}
        onClick={() => save.mutate()}
      >
        {t("save")}
      </Button>
    </Panel>
  );
}

const THEMES = [
  { choice: "light", icon: Sun },
  { choice: "dark", icon: Moon },
  { choice: "system", icon: Monitor },
] as const;

/**
 * §13's *"Appearance and reduced motion"*.
 *
 * The theme is real and persists: `applyThemeChoice` writes the choice and every subscriber follows
 * it, including the two-state switch in the top bar. All three choices are offered here because
 * there is room to label them — the header has room for one glyph, which is why it has two.
 *
 * **Reduced motion is not a setting this product owns.** It comes from the operating system, the
 * whole interface already honours `prefers-reduced-motion`, and a toggle here would either do
 * nothing or silently disagree with the system. So this reports what the system currently says and
 * where to change it. A switch would have been easier to build and would have been a lie.
 */
export function AppearanceSection() {
  const t = useTranslations("settings");
  const { choice, resolved } = useTheme();
  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  return (
    <Panel title={t("appearance.title")} description={t("appearance.description")}>
      <fieldset>
        <legend className="mb-2 text-sm font-medium">{t("appearance.theme")}</legend>
        <div className="flex flex-wrap gap-2">
          {THEMES.map((option) => {
            const Icon = option.icon;
            const chosen = choice === option.choice;
            return (
              <label
                key={option.choice}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm",
                  chosen ? "border-primary bg-muted" : "border-border bg-card",
                  "focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--ub-focus)]",
                )}
              >
                <input
                  type="radio"
                  name="theme"
                  value={option.choice}
                  checked={chosen}
                  onChange={() => applyThemeChoice(option.choice)}
                  className="sr-only"
                />
                <Icon aria-hidden className="size-4" />
                {t(`appearance.${option.choice}` as "appearance.light")}
              </label>
            );
          })}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          {t("appearance.showing", {
            theme: t(`appearance.${resolved}` as "appearance.light"),
          })}
        </p>
      </fieldset>

      <div className="border-t border-border pt-3">
        <p className="text-sm font-medium">{t("appearance.motion")}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {reduced ? t("appearance.motionReduced") : t("appearance.motionFull")}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">{t("appearance.motionWhere")}</p>
      </div>
    </Panel>
  );
}

/**
 * §13's *"Notifications and quiet hours"* — the six categories, quiet hours and the digest.
 *
 * All of it real since Gate 7.5. The preferences are per category with two deliveries, because that
 * is what the backend stores; nothing here invents a channel the product cannot send on.
 */
export function NotificationsSection({ user }: { user: CurrentUser }) {
  const t = useTranslations("settings");
  const queryClient = useQueryClient();

  const preferences = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: ({ signal }) => fetchNotificationPreferences(signal),
  });
  const settings = useQuery({
    queryKey: ["notification-settings"],
    queryFn: ({ signal }) => fetchNotificationSettings(signal),
  });

  //  One row at a time, because that is what the route takes: the key is derived from the
  //  category and the delivery, so a retry of *this* change reuses it.
  const savePreference = useMutation({
    mutationFn: (row: NotificationPreference) =>
      saveNotificationPreference(row.category, {
        in_app: row.in_app,
        email: row.email,
        delivery: row.delivery,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["notification-preferences"] });
    },
  });
  const saveQuiet = useMutation({
    mutationFn: (input: {
      quiet_hours_enabled: boolean;
      quiet_from: string;
      quiet_to: string;
      digest_hour: number;
      timezone: string;
    }) => saveNotificationSettings(input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["notification-settings"] });
    },
  });

  return (
    <Panel title={t("notifications.title")} description={t("notifications.description")}>
      <QueryStates
        isPending={preferences.isPending || settings.isPending}
        error={preferences.error ?? settings.error}
        isEmpty={false}
        emptyTitle=""
        onRetry={() => {
          void preferences.refetch();
          void settings.refetch();
        }}
      >
        {preferences.data && settings.data ? (
          <div className="space-y-4">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th scope="col" className="pb-2">
                    {t("notifications.category")}
                  </th>
                  <th scope="col" className="pb-2">
                    {t("notifications.inApp")}
                  </th>
                  <th scope="col" className="pb-2">
                    {t("notifications.email")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {preferences.data.map((row) => (
                  <tr key={row.category} className="border-b border-border last:border-0">
                    <td className="py-2">
                      {t(`notifications.categories.${row.category}` as "notifications.categories.approval")}
                    </td>
                    {(["in_app", "email"] as const).map((channel) => (
                      <td key={channel} className="py-2">
                        <input
                          type="checkbox"
                          aria-label={`${row.category} ${channel}`}
                          checked={row[channel]}
                          disabled={savePreference.isPending}
                          onChange={(event) =>
                            savePreference.mutate({ ...row, [channel]: event.target.checked })
                          }
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>

            <QuietHours
              settings={settings.data}
              timezone={user.timezone}
              busy={saveQuiet.isPending}
              onSave={(input) => saveQuiet.mutate(input)}
            />

            {savePreference.isError || saveQuiet.isError ? (
              <Alert tone="danger" title={t("notSaved")}>
                {((savePreference.error ?? saveQuiet.error) as Error).message}
              </Alert>
            ) : null}
          </div>
        ) : null}
      </QueryStates>
    </Panel>
  );
}

function QuietHours({
  settings,
  timezone,
  busy,
  onSave,
}: {
  //  `quiet_from` and `quiet_to` are nullable in the contract: somebody who has never set quiet
  //  hours has none, which is a different fact from midnight to midnight.
  settings: {
    quiet_hours_enabled: boolean;
    quiet_from?: string | null;
    quiet_to?: string | null;
    digest_hour: number;
    timezone: string;
  };
  timezone: string;
  busy: boolean;
  onSave: (input: {
    quiet_hours_enabled: boolean;
    quiet_from: string;
    quiet_to: string;
    digest_hour: number;
    timezone: string;
  }) => void;
}) {
  const t = useTranslations("settings");
  const [enabled, setEnabled] = useState(settings.quiet_hours_enabled);
  const [from, setFrom] = useState(settings.quiet_from ?? "21:00:00");
  const [to, setTo] = useState(settings.quiet_to ?? "08:00:00");
  const [hour, setHour] = useState(settings.digest_hour);

  return (
    <div className="space-y-3 border-t border-border pt-3">
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        {t("notifications.quietHours")}
      </label>

      <div className="grid gap-3 sm:grid-cols-3">
        <Field label={t("notifications.from")} htmlFor="quiet-from">
          {(field) => (
            <Input
              {...field}
              type="time"
              value={from.slice(0, 5)}
              disabled={!enabled}
              onChange={(event) => setFrom(`${event.target.value}:00`)}
            />
          )}
        </Field>
        <Field label={t("notifications.to")} htmlFor="quiet-to">
          {(field) => (
            <Input
              {...field}
              type="time"
              value={to.slice(0, 5)}
              disabled={!enabled}
              onChange={(event) => setTo(`${event.target.value}:00`)}
            />
          )}
        </Field>
        <Field label={t("notifications.digestHour")} hint={t("notifications.digestHint")} htmlFor="digest-hour">
          {(field) => (
            <Input
              {...field}
              type="number"
              min={0}
              max={23}
              value={hour}
              onChange={(event) => setHour(Number(event.target.value))}
            />
          )}
        </Field>
      </div>

      {/*  One timezone, and it is the profile's. The digest keeps its own copy of it in the
          database and `PATCH /auth/me` writes both, so this states which one is in force rather
          than offering a second control that could disagree with the first. */}
      <p className="text-xs text-muted-foreground">
        {t("notifications.inZone", { zone: timezone })}
      </p>

      <Button
        variant="secondary"
        size="sm"
        busy={busy}
        onClick={() =>
          onSave({
            quiet_hours_enabled: enabled,
            quiet_from: from,
            quiet_to: to,
            digest_hour: hour,
            timezone,
          })
        }
      >
        {t("save")}
      </Button>
    </div>
  );
}

/**
 * §13's *"Security, MFA and sessions"*.
 *
 * Sessions are real: where this account is signed in, and the way to end one. MFA is not built, and
 * says so — a security screen that implied a second factor was configured would be the worst place
 * in the product to be wrong.
 *
 * Changing a password has no route either. What exists is the reset link, which is the same
 * mechanism a person uses when they have forgotten it, and this says so rather than showing a
 * change-password form that would post to nothing.
 */
export function SecuritySection({ user }: { user: CurrentUser }) {
  const t = useTranslations("settings");
  const queryClient = useQueryClient();
  const signOut = useSignOut();

  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: ({ signal }) => fetchSessions(signal),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => revokeSession(id),
    onSuccess: (_result, id) => {
      const wasCurrent = sessions.data?.find((one) => one.id === id)?.is_current;
      if (wasCurrent) {
        //  Ending your own session means being signed out. Saying so first is the honest order.
        signOut.mutate();
        return;
      }
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  return (
    <div className="space-y-4">
      <Panel title={t("security.sessionsTitle")} description={t("security.sessionsDescription")}>
        <QueryStates
          isPending={sessions.isPending}
          error={sessions.error}
          isEmpty={(sessions.data ?? []).length === 0}
          emptyTitle={t("security.noSessions")}
          onRetry={() => void sessions.refetch()}
        >
          <ul className="divide-y divide-border">
            {(sessions.data ?? []).map((one) => (
              <li key={one.id} className="flex items-start justify-between gap-3 py-2.5">
                <div className="min-w-0 text-sm">
                  <p className="flex items-center gap-2 font-medium">
                    {one.ip_address ?? t("security.unknownAddress")}
                    {one.is_current ? (
                      <Badge tone="success">{t("security.thisBrowser")}</Badge>
                    ) : null}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {one.user_agent ?? t("security.unknownDevice")}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {t("security.lastSeen", {
                      when: formatDateTimeWithZone(
                        one.last_seen_at,
                        contextFor(user.timezone),
                      ),
                    })}
                  </p>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  busy={revoke.isPending}
                  onClick={() => revoke.mutate(one.id)}
                >
                  {one.is_current ? t("security.endAndSignOut") : t("security.end")}
                </Button>
              </li>
            ))}
          </ul>
        </QueryStates>

        {revoke.isError ? (
          <Alert tone="danger" title={t("security.notEnded")}>
            {(revoke.error as Error).message}
          </Alert>
        ) : null}
      </Panel>

      <Panel title={t("security.passwordTitle")}>
        <p className="text-sm text-muted-foreground">{t("security.passwordBody")}</p>
      </Panel>

      <Panel title={t("security.mfaTitle")}>
        <Alert tone="info" title={t("notBuiltTitle", { gate: "Gate 8" })}>
          {t("security.mfaBody")}
        </Alert>
      </Panel>
    </div>
  );
}

/**
 * A category that does not exist yet, said plainly.
 *
 * Not a mock, not a disabled form, and not a spinner that never resolves: a sentence about what
 * will be here and which gate builds it. `CLAUDE.md`: *"Never show a control that does not do what
 * it says."* The safest control is the one that is not drawn.
 */
export function NotBuiltSection({ id, gate }: { id: string; gate: string }) {
  const t = useTranslations("settings");

  return (
    <Panel title={t(`category.${id}` as "category.general")}>
      <Alert tone="info" title={t("notBuiltTitle", { gate })}>
        {t(`willHold.${id}` as "willHold.general")}
      </Alert>
    </Panel>
  );
}
