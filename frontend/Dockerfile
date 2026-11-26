FROM node:22-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG ARCHIVE_API_ORIGIN
RUN test -n "$ARCHIVE_API_ORIGIN"
ENV ARCHIVE_API_ORIGIN=$ARCHIVE_API_ORIGIN
RUN npm run build

FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
ARG ARCHIVE_API_ORIGIN
ENV ARCHIVE_API_ORIGIN=$ARCHIVE_API_ORIGIN
COPY --from=build --chown=node:node /app ./
USER node
EXPOSE 3017
CMD ["npm", "run", "start", "--", "-H", "0.0.0.0", "-p", "3017"]
