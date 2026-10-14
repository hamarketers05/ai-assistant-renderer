/// <reference types="@cloudflare/workers-types" />

interface Env {
  DB: D1Database;
  W0_AUTH_TOKEN?: string | undefined;
  APP_ENV?: string;
  APP_VERSION?: string;
}


declare module "*?raw" {
  const content: string;
  export default content;
}
