/**
 * The bell — §12, as the browser calls it.
 *
 * **There is no `createNotification`.** A notification exists because something happened that the
 * product decided was worth telling somebody; the backend has no route to make one, and neither
 * does this.
 *
 * Every call is implicitly scoped to the signed-in person by the server. Nothing here takes a
 * membership id, because there is no way to read somebody else's bell — deliberately.
 */

import { request } from "./client";
import type {
  BellNotification,
  NotificationCounts,
  NotificationPreference,
  NotificationSettings,
} from "./contract";
import { operationKey } from "./idempotency";

/** §12's three tabs: All, Unread, Action required. */
export type NotificationTab = "all" | "unread" | "action_required";

export async function fetchNotifications(
  tab: NotificationTab = "all",
  signal?: AbortSignal,
): Promise<BellNotification[]> {
  return request<BellNotification[]>(`/notifications?tab=${tab}&limit=30`, {
    ...(signal ? { signal } : {}),
  });
}

export async function fetchNotificationCounts(
  signal?: AbortSignal,
): Promise<NotificationCounts> {
  return request<NotificationCounts>("/notifications/counts", {
    ...(signal ? { signal } : {}),
  });
}

export async function markNotificationRead(id: string): Promise<void> {
  await request(`/notifications/${id}/read`, {
    method: "POST",
    idempotencyKey: operationKey("notification-read", id),
  });
}

export async function markAllNotificationsRead(): Promise<void> {
  await request("/notifications/read-all", {
    method: "POST",
    //  Not derived from the set being cleared — that set changes between the click and the
    //  request. "Clear my bell" is one intent whenever it is sent.
    idempotencyKey: operationKey("notifications-read-all"),
  });
}

export async function fetchNotificationPreferences(
  signal?: AbortSignal,
): Promise<NotificationPreference[]> {
  return request<NotificationPreference[]>("/notifications/preferences", {
    ...(signal ? { signal } : {}),
  });
}

export async function saveNotificationPreference(
  category: string,
  body: { in_app: boolean; email: boolean; delivery: string },
): Promise<NotificationPreference> {
  return request<NotificationPreference>("/notifications/preferences", {
    method: "PUT",
    idempotencyKey: operationKey("notification-pref", category, body.delivery),
    body: { category, ...body },
  });
}

export async function fetchNotificationSettings(
  signal?: AbortSignal,
): Promise<NotificationSettings> {
  return request<NotificationSettings>("/notifications/settings", {
    ...(signal ? { signal } : {}),
  });
}

export async function saveNotificationSettings(
  body: NotificationSettings,
): Promise<NotificationSettings> {
  return request<NotificationSettings>("/notifications/settings", {
    method: "PUT",
    idempotencyKey: operationKey(
      "notification-settings",
      String(body.digest_hour),
      String(body.quiet_hours_enabled),
    ),
    body,
  });
}
