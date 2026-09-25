import { env } from "cloudflare:workers";
import { runInDurableObject } from "cloudflare:test";
import { beforeAll } from "vitest";

/**
 * Tests freeze Date at fixed moments (mostly Monday, September 14, 2026), but
 * workerd runs Durable Object alarms on the real clock. Once those moments are in
 * the past, every alarm the code sets fires at once in the background and races
 * the test's own runDurableObjectAlarm, so results depended on the day the suite
 * ran. Stored alarm times are shifted into the real future by a fixed offset and
 * shifted back on read: alarms run only when a test runs them, and getAlarm still
 * reports the time the code chose. Production code is unchanged.
 */
const DAY = 86_400_000;
const OFFSET = Math.max(0, Date.now() - Date.parse("2026-09-01T00:00:00Z")) + 30 * DAY;

beforeAll(async () => {
  await runInDurableObject(env.ISSUER_POLLER.getByName("__alarm-clock__"), async (_instance, state) => {
    const proto = Object.getPrototypeOf(state.storage) as Record<string, unknown>;
    if (proto.__alarmOffset) return;
    const setAlarm = proto.setAlarm as (this: DurableObjectStorage, time: number | Date, options?: unknown) => Promise<void>;
    const getAlarm = proto.getAlarm as (this: DurableObjectStorage, options?: unknown) => Promise<number | null>;
    Object.defineProperties(proto, {
      __alarmOffset: { value: OFFSET },
      setAlarm: { configurable: true, writable: true,
        value(this: DurableObjectStorage, time: number | Date, options?: unknown) { return setAlarm.call(this, Number(time) + OFFSET, options); } },
      getAlarm: { configurable: true, writable: true,
        async value(this: DurableObjectStorage, options?: unknown) {
          const time = await getAlarm.call(this, options);
          return time === null ? null : time - OFFSET;
        } },
    });
  });
});
