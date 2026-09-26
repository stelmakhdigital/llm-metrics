# llm-metrics web

Next.js 15 (App Router, TS, Tailwind v4, shadcn-style UI, uPlot). Порт 3000,
API-запросы проксируются на бекенд через rewrites (`/api/*` → `$API_URL/api/*`,
по умолчанию `http://127.0.0.1:8100`).

## Команды

```sh
npm install      # зависимости
npm run dev      # dev-сервер на :3000
npm run build    # прод-сборка
npm start        # запуск прод-сборки
```

Dev вместе с бэком: `make dev-web` (из корня репо).

## Docker

```sh
docker build -t llm-metrics-web web/
docker run -p 3000:3000 -e API_URL=http://api:8100 llm-metrics-web
```
