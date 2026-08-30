import type { Metadata, Viewport } from "next";

import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";

import { Providers } from "./providers";
import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme-script";
import { SkipLink } from "@/ui/skip-link";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "UBOSS AI",
    template: "%s · UBOSS AI",
  },
  description: "Governed human and AI work: objectives, jobs, agents and approvals.",
  // Nothing in this product should ever appear in a search index or a link preview.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // The theme colour is not switched here; the bootstrap script below sets `color-scheme` on the
  // document, which is what the browser actually uses to paint form controls and scrollbars.
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  //  Resolved on the server and handed to the client provider, so a component reads its strings
  //  without every page fetching a catalogue.
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    <html lang={locale} suppressHydrationWarning>
      <head>
        {/*
          Runs during parsing, before the first paint, so a person who chose dark never sees a
          white flash. `suppressHydrationWarning` above is required because this script changes
          the <html> class before React compares the markup it rendered on the server.
        */}
        <script
          dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }}
        />
      </head>
      <body>
        <NextIntlClientProvider locale={locale} messages={messages}>
          {/*  Inside the provider: it reads its label from the catalogue like everything else,
              and a component above the provider has no messages to read. */}
          <SkipLink />
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
