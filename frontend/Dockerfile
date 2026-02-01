FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json /app/
RUN npm ci

COPY . /app/
RUN npm run build


FROM nginx:1.27-alpine

ENV PORT=80 \
    API_UPSTREAM=http://backend:8000

# Official nginx image supports envsubst templates under /etc/nginx/templates/
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

