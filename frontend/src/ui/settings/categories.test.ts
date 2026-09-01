/**
 * Every notification category has a label, and the list is §12's own.
 *
 * The Settings screen labels each row with a dynamic key — `t(`categories.${row.category}`)` — and
 * `messages.test.ts` cannot check those: it skips dynamic keys, and its own header says that shape
 * is *"the most likely to hide one"*. It hid one here. The first version of the section invented six
 * plausible categories (`approval`, `task`, `run`, …) instead of reading the six the backend has,
 * and every row rendered `MISSING_MESSAGE` until a browser test opened the panel.
 *
 * So the list lives here, copied from `backend/src/uboss/modules/notifications/models.py`, and a
 * seventh category — or a renamed one — fails this test instead of a screen.
 */
import { describe, expect, it } from "vitest";

import messages from "@/messages/en.json";

/** §12: *"task/assignment, approval/input, Agent failure/result, schedule/lifecycle,
 *  mention/comment and security/admin"*. */
const CATEGORIES = [
  "task_assignment",
  "approval_input",
  "agent_result",
  "schedule_lifecycle",
  "mention_comment",
  "security_admin",
] as const;

describe("notification categories", () => {
  it.each(CATEGORIES)("has a label for %s", (category) => {
    expect(
      messages.settings.notifications.categories[
        category as keyof typeof messages.settings.notifications.categories
      ],
    ).toBeTruthy();
  });

  it("labels exactly the six and no more", () => {
    //  A label with no category behind it is a row nobody will ever see, and usually the sign of a
    //  category that was renamed on one side only.
    expect(Object.keys(messages.settings.notifications.categories).sort()).toEqual(
      [...CATEGORIES].sort(),
    );
  });
});
