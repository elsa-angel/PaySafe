# PaySafe frontend (React + Vite + pnpm)

```bash
pnpm install        # use pnpm 8 (lockfile v6)
pnpm dev            # http://localhost:5173 (proxies /api to Django on 127.0.0.1:8000)
pnpm lint
pnpm build
```

Regular users and administrators share the same login page. After sign-in the backend-provided `role`
decides where you land: users go to the dashboard, administrators to `/admin`. Route guards are a
convenience only; every admin API call is authorised by the server.

Admin pages live in `src/pages/admin/` and reuse the existing PaySafe components and CSS tokens. Charts are
small dependency-free SVG components in `src/components/admin/Charts.jsx`.
