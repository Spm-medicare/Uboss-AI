import createNextIntlPlugin from "next-intl/plugin";
import type { NextConfig } from "next";

//  Points next-intl at src/i18n/request.ts, which resolves the locale and loads its messages.
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const config: NextConfig = {
  //  Fail the build on a type error. Shipping a known-broken build because a flag suppressed
  //  the report is how "it compiled" stops meaning anything.
  //
  //  Next 16 no longer runs ESLint during `next build`, so lint is a separate CI step
  //  (`npm run lint`) rather than something this file can enforce.
  typescript: { ignoreBuildErrors: false },

  reactStrictMode: true,

  // Next.js blocks development assets requested through a different origin by default. Keep the
  // ngrok preview explicit rather than allowing every host; this is development-only and does
  // not change the production origin policy.
  allowedDevOrigins: ["crunching-dramatize-underline.ngrok-free.dev"],

  //  A single self-contained server bundle, so the container does not carry node_modules.
  output: "standalone",

  //  The API's version and build are not the browser's business.
  poweredByHeader: false,

  //  Next's own development badge — a black circle in the bottom-left corner of every page.
  //  It is an overlay, not part of this app, and it sat directly on top of the sidebar's foot
  //  where it read as one of our controls. Off, so what is on screen is ours.
  devIndicators: false,

  /*  The API, served from this app's own origin.

      `NEXT_PUBLIC_API_BASE_URL` is baked into the browser bundle, so an absolute
      `http://localhost:8001` is only correct for a browser running on this machine. Anything else
      — a tunnel, a phone on the same network, a colleague's laptop — resolves `localhost` to
      itself and the call never arrives; sign-in then reports, accurately, that it could not reach
      UBOSS.

      Proxying keeps the browser on one origin, which also keeps the session cookie first-party:
      it is `SameSite=Lax` with no domain, so a page and an API on different hosts would not
      exchange it and signing in would appear to work without sticking.

      `UBOSS_API_ORIGIN` is read on the server only — no `NEXT_PUBLIC_` prefix — because it is the
      address this process dials, not one the browser needs to know. */
  async rewrites() {
    const api = process.env.UBOSS_API_ORIGIN ?? "http://localhost:8001";
    return [{ source: "/api/v1/:path*", destination: `${api}/api/v1/:path*` }];
  },

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          //  The browser is never asked for a camera, a microphone or a location, so it is told
          //  not to offer them. A permission that is never requested cannot be abused.
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), interest-cohort=()",
          },
        ],
      },
    ];
  },
};

export default withNextIntl(config);
