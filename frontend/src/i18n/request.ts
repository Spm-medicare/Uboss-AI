/**
 * Which locale this request renders in, and the messages for it.
 *
 * **The locale is not in the URL.** PLAN §3 fixes the navigation, and putting `/en/…` in front of
 * every path would change every link in the product for a second language that does not exist
 * yet. It comes from the signed-in person's setting instead — which is where it belongs, because
 * a person's language is theirs and not their bookmark's.
 *
 * Until Settings exists (Gate 8) that setting has nowhere to be changed, so this always resolves
 * to English. The plumbing is real; the choice is not offered, and nothing pretends it is.
 */

import { getRequestConfig } from "next-intl/server";

import { DEFAULT_LOCALE } from "./config";

export default getRequestConfig(async () => {
  const locale = DEFAULT_LOCALE;

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
    //  Everything stored is UTC; everything shown is local. The zone is resolved per component
    //  from the signed-in person, falling back to their organisation — not here, because a
    //  server render has no session to read yet.
    timeZone: "UTC",
  };
});
