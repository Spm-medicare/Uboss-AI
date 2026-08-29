import type { NextConfig } from "next";

const config: NextConfig = {
  //  Fail the build on a type error. Shipping a known-broken build because a flag suppressed
  //  the report is how "it compiled" stops meaning anything.
  //
  //  Next 16 no longer runs ESLint during `next build`, so lint is a separate CI step
  //  (`npm run lint`) rather than something this file can enforce.
  typescript: { ignoreBuildErrors: false },

  reactStrictMode: true,

  //  A single self-contained server bundle, so the container does not carry node_modules.
  output: "standalone",

  //  The API's version and build are not the browser's business.
  poweredByHeader: false,

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

export default config;
