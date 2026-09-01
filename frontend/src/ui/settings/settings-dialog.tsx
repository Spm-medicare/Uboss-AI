"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { useSession } from "@/lib/auth/use-session";
import { QueryStates } from "@/ui";
import { Dialog } from "@/ui/dialog";
import { CATEGORIES, type SettingsCategory } from "@/ui/settings/catalogue";
import { SettingsPanel } from "@/ui/settings/panel";

/**
 * Settings over the top of whatever you were doing.
 *
 * §13 allows either: *"Dedicated Settings page/panel"*. A panel is the better half of that choice
 * for this product — changing your timezone or your notifications is a two-second errand in the
 * middle of something else, and a full navigation makes you find your way back. The route stays for
 * a link somebody sends; this is what the gear opens.
 *
 * Reuses `ui/dialog.tsx` rather than building a second modal: the focus trap, the Escape handler,
 * the scroll lock and the returned focus are all there and all easy to get subtly wrong twice.
 *
 * The open category lives in component state and is gone when the panel closes. That is deliberate:
 * a panel is not a place, and leaving `?c=security` behind in the URL of the screen underneath would
 * make the back button undo somebody else's navigation.
 */
export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("settings");
  const { user, isLoading, error } = useSession();
  const [chosen, setChosen] = useState<SettingsCategory>(CATEGORIES[0]!);

  return (
    <Dialog
      title={t("title")}
      description={t("overlayDescription")}
      onClose={onClose}
      size="wide"
    >
      <QueryStates isPending={isLoading} error={error} isEmpty={false} emptyTitle="">
        {user ? (
          <SettingsPanel user={user} chosen={chosen} onChoose={setChosen} />
        ) : null}
      </QueryStates>
    </Dialog>
  );
}
