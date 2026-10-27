# Image: builds the React app with Node, then serves the static files with unprivileged nginx on port 8080.
# Build from the repository root (the npm workspace lockfile lives there):
#   docker build -f apps/web/Dockerfile -t customer-compass-web .
FROM node:26-alpine AS build
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
RUN npm ci --workspace=@customer-compass/web
COPY apps/web apps/web
RUN npm run build --workspace=@customer-compass/web

FROM nginxinc/nginx-unprivileged:1.31-alpine
# pull in Alpine security fixes published after the base image was built, then drop root again
USER root
RUN apk upgrade --no-cache
USER nginx
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
EXPOSE 8080
