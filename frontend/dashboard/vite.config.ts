import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Base path is env-driven so the same source can be built for:
//   - the normal standalone deployment (base "/", default), and
//   - the single-service DEMO deployment, where the SPA is served by the
//     FastAPI demo wrapper under /dashboard/:
//       VITE_BASE=/dashboard/ npm run build:demo
// import.meta.env.BASE_URL in the app mirrors this value.
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
  server: { port: 5173 },
});
