import express from 'express';
import { waitForGel } from './gel/client.js';
import { redis, ROUTE_KEYS } from './redis/client.js';
import { attachFaultChannel, IS_TEST } from './lib/faults.js';
import { eventsRouter } from './routes/events.js';
import { queriesRouter } from './routes/queries.js';
import { adminRouter } from './routes/admin.js';
import { reconcileRouting } from './rebuild/alias-switch.js';

const port = Number(process.env.PORT ?? 8080);

async function main(): Promise<void> {
  await waitForGel(Number(process.env.GEL_READY_TIMEOUT_MS ?? 300_000));
  await redis.ping();

  if (IS_TEST) attachFaultChannel(process.env.REDIS_URL ?? 'redis://127.0.0.1:6379');

  // If the last run died inside a cutover, routing may be torn; if the cache
  // was restarted, routing may be gone. Both are resolved before the first
  // request is answered, so no reader is ever served a feed from one generation
  // and counts from the other, and none is sent to a generation that has been
  // retired because the cache could not remember it had been.
  //
  // This runs before the default below rather than after it. Defaulting first
  // would write v1 over three empty keys and leave nothing to reconcile: the
  // store would still know a cutover had happened and nobody would ask it.
  const routing = await reconcileRouting();
  if (routing === 'repaired') console.log('routing was torn on startup and has been completed');
  if (routing === 'restored') console.log('routing was missing on startup and has been read back from the store');

  // Routing defaults to the generation that has always served: a restart must
  // never silently repoint readers.
  for (const key of ROUTE_KEYS) await redis.setnx(key, 'v1');

  const app = express();
  app.use(express.json({ limit: '1mb' }));
  app.get('/healthz', (_req, res) => res.json({ ok: true }));
  app.use(eventsRouter);
  app.use(queriesRouter);
  app.use(adminRouter);

  app.listen(port, '127.0.0.1', () => {
    console.log(`event-feed listening on ${port}`);
  });
}

main().catch((err) => {
  console.error('startup failed:', err);
  process.exit(1);
});
