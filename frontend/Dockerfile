# The web image.
#
# Three stages: dependencies, build, run. The runtime carries the standalone server Next produces
# and none of node_modules — a production image should not contain a package manager or the
# source it built from.

FROM node:24-slim AS deps
WORKDIR /build
COPY package.json package-lock.json ./
# `npm ci` installs exactly the lock file and fails if package.json disagrees with it.
RUN npm ci


FROM node:24-slim AS build
WORKDIR /build
COPY --from=deps /build/node_modules ./node_modules
COPY . .

# Baked in at build time, because Next inlines NEXT_PUBLIC_* into the JavaScript it emits. That
# means one image per environment — which is the honest consequence, not a workaround. Nothing
# secret may carry this prefix; those values ship to every browser.
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

# Fails on a type error — next.config.ts sets ignoreBuildErrors: false.
RUN npm run build


FROM node:24-slim AS runtime
RUN groupadd --gid 10001 uboss \
 && useradd --uid 10001 --gid uboss --no-create-home --shell /usr/sbin/nologin uboss

WORKDIR /app

# `output: "standalone"` produces a server with only the modules it actually uses. The static and
# public directories are copied alongside it because the standalone output does not include them.
COPY --from=build --chown=uboss:uboss /build/.next/standalone ./
COPY --from=build --chown=uboss:uboss /build/.next/static ./.next/static
COPY --from=build --chown=uboss:uboss /build/public ./public

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

USER uboss
EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:3000/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
