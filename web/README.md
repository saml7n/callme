# CallMe — Web UI

React + TypeScript + Vite frontend for the CallMe AI receptionist.

## Development

```bash
npm install      # Install dependencies
npm run dev      # Start dev server → http://localhost:5173
npm test         # Run Vitest test suite
npm run build    # Production build → dist/
```

The Vite dev server proxies `/api` and `/ws` to `http://localhost:3000` (see `vite.config.ts`), so make sure the server is running.

## Stack

- **React 19** with React Router v7
- **Vite 6** with HMR
- **Tailwind CSS** + **shadcn/ui** components
- **Vitest** + React Testing Library for tests
