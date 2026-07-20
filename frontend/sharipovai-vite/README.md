# SharipovAI Vite Frontend

Isolated React + Vite + TypeScript + Tailwind frontend for the secure SharipovAI chat.

## Security model

- The browser never imports a Gemini SDK and never receives `GEMINI_API_KEY`.
- `VITE_*` variables are public build-time values. They must not contain secrets.
- The frontend sends same-origin requests to `POST /api/ai/chat`.
- The FastAPI backend reads `GEMINI_API_KEY` from server environment and calls Gemini.
- Chat requests require an authenticated SharipovAI session in production.
- The gateway validates origin, body schema, message length, history length and request rate.
- Provider errors are sanitized before returning to the browser.

## Structure

```text
src/
├── api/                 # typed browser API clients
├── app/                 # application root
├── components/
│   ├── chat/            # chat presentation and composer
│   ├── dashboard/       # responsive dashboard shell
│   └── ui/              # reusable error boundary
├── hooks/               # useChat, debounce and theme logic
├── lib/                 # ids and schema-validated session storage
├── styles/              # Tailwind and accessibility styles
└── types/               # domain contracts
```

## Local development

Backend, from repository root:

```bash
cp .env.example .env
# Put GEMINI_API_KEY only in the root server .env.
python -m uvicorn dashboard:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:

```bash
cd frontend/sharipovai-vite
cp .env.example .env.local
npm install
npm run typecheck
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to `http://127.0.0.1:8000`.

## Production build

```bash
cd frontend/sharipovai-vite
npm ci
npm run build
npm run preview
```

Use an HTTPS reverse proxy and serve the generated `dist/` directory. Keep API and frontend on the same origin whenever possible.

## Key rotation

If a Gemini key ever appeared in source code, browser DevTools, a screenshot or Git history:

1. create a replacement restricted/auth key;
2. update server secret storage;
3. deploy and verify the backend gateway;
4. revoke the exposed key;
5. review provider usage and billing alerts.
