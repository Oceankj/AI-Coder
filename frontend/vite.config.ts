// Author: Ching Kao
// Student ID: 85768427
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const port = Number(env.FRONTEND_PORT || 5173);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('FRONTEND_PORT must be an integer between 1 and 65535.');
  }
  return {
    server: { host: env.FRONTEND_HOST || '127.0.0.1', port, strictPort: true },
  };
});
