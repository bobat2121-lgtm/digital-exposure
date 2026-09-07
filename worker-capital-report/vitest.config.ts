import { defineConfig } from "vitest/config";
import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
// The test plugin's bundled runtime lags the current compatibility date. Use the
// exact workerd binary shipped with our pinned production Wrangler instead.
process.env.MINIFLARE_WORKERD_PATH = createRequire(require.resolve("wrangler"))("workerd").default;
process.env.SEC_USER_AGENT = "Capital Report tests test@digital-credit.test";
process.env.ADMIN_TOKEN = "offline-test-token-0000000000000000000000";
export default defineConfig({
  plugins: [cloudflareTest({ wrangler: { configPath: "./wrangler.jsonc" },
    miniflare: { bindings: { SEC_USER_AGENT: "Capital Report tests test@digital-credit.test", ADMIN_TOKEN: "offline-test-token-0000000000000000000000" } } })],
  test: { include: ["test/**/*.test.ts"], fileParallelism: false },
});
