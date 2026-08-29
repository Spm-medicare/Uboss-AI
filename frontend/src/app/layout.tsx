import type { Metadata, Viewport } from "next";

import { Providers } from "./providers";
import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme-script";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "UBOSS",
    template: "%s · UBOSS",
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

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
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
        <a className="ub-skip-link" href="#main">
          Skip to main content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
