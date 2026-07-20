FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/sharipovai-vite/package.json ./package.json
RUN npm install --ignore-scripts --no-audit --no-fund
COPY frontend/sharipovai-vite/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
