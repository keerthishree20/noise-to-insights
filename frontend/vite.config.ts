import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The backend's CORS policy allows this origin, so fail loudly on a port
    // clash instead of silently moving to 5174 and getting blocked.
    strictPort: true,
  },
});
