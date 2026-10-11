import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the console calls the core through this proxy, so no CORS setup is needed.
// Point it elsewhere with: AA_CORE_URL=http://host:8000 npm run dev
const core = process.env.AA_CORE_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": core, "/health": core } },
  preview: { port: 5173, proxy: { "/v1": core, "/health": core } },
});
