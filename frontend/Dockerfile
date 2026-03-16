# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci

FROM node:22-bookworm-slim AS builder
ENV NODE_ENV=production
WORKDIR /app

# Build arguments used by Vite (exposed at build time)
ARG VITE_ENABLE_PROJECTS

ENV VITE_ENABLE_PROJECTS=$VITE_ENABLE_PROJECTS

COPY --from=deps /app/node_modules ./node_modules
COPY . ./
RUN npm run build

# Minimal production image — only static files + a lightweight server
FROM node:22-bookworm-slim AS runner
RUN npm install -g serve@14
WORKDIR /app
COPY --from=builder /app/dist ./dist

EXPOSE 3000

# serve -s enables SPA fallback (all routes → index.html)
CMD ["serve", "-s", "dist", "-l", "3000"]
