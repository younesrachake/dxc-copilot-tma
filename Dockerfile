# ─────────────────────────────────────────────────────────────
# Stage 1 — Build the Angular application
# ─────────────────────────────────────────────────────────────
FROM node:26-alpine AS builder

WORKDIR /app

# Install dependencies first (layer cache)
COPY package*.json ./
RUN npm ci --prefer-offline

# Copy source and build for production
COPY . .
RUN npm run build -- --configuration production

# ─────────────────────────────────────────────────────────────
# Stage 2 — Serve with Nginx (distroless-like, no shell)
# ─────────────────────────────────────────────────────────────
FROM nginx:1.25-alpine AS runtime

# Remove default nginx static assets
RUN rm -rf /usr/share/nginx/html/*

# Copy compiled Angular app
COPY --from=builder /app/dist/dxc-copilot-tma /usr/share/nginx/html

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
