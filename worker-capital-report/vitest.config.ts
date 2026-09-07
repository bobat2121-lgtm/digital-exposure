import { defineConfig } from "vitest/config";
import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
// The test plugin's bundled runtime lags the current compatibility date. Use the
// exact workerd binary shipped with our pinned production Wrangler instead.
process.env.MINIFLARE_WORKERD_PATH = createRequire(require.resolve("wrangler"))("workerd").default;
process.env.SEC_USER_AGENT = "Capital Report tests test@digital-credit.test";
process.env.ADMIN_TOKEN = "offline-test-token-0000000000000000000000";
process.env.STREAMLIT_ACK_TOKEN = "offline-streamlit-ack-token-000000000000000000";
process.env.DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/111111111111111111/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
export default defineConfig({
  plugins: [cloudflareTest({ wrangler: { configPath: "./wrangler.jsonc" },
    miniflare: { bindings: { SEC_USER_AGENT: process.env.SEC_USER_AGENT, ADMIN_TOKEN: process.env.ADMIN_TOKEN,
      STREAMLIT_ACK_TOKEN: process.env.STREAMLIT_ACK_TOKEN, DISCORD_WEBHOOK_URL: process.env.DISCORD_WEBHOOK_URL } } })],
  test: { include: ["test/**/*.test.ts"], fileParallelism: false },
});
