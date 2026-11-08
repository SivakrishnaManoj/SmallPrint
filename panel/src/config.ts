export const SERVER_URL: string =
  (import.meta as unknown as { env: Record<string, string> }).env.VITE_SERVER_URL ||
  "http://localhost:8000";
