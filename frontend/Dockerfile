# --- Builder ---
FROM oven/bun:1-alpine AS builder
WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .
RUN bun run build

# --- Runtime ---
# Runs as uid 101 with no root master process, so it listens on 8080 rather
# than the privileged port 80 (see nginx.conf and the compose port mapping).
FROM nginxinc/nginx-unprivileged:1-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
