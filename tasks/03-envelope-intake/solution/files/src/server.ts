import express from 'express';

import { databasePath } from './db/client';
import { egressRouter } from './routes/egress';
import { intakeRouter } from './routes/intake';
import { repliesRouter } from './routes/replies';
import { ticketAdminRouter } from './routes/ticketAdmin';
import { ticketReadRouter } from './routes/ticketRead';

export function createApp(): express.Express {
  const app = express();
  app.use(express.json({ limit: '1mb' }));

  app.get('/health', (_req, res) => {
    res.status(200).json({ status: 'ok', store: databasePath() });
  });

  app.use(ticketAdminRouter());
  app.use(intakeRouter());
  app.use(ticketReadRouter());
  app.use(repliesRouter());
  app.use(egressRouter());

  return app;
}

if (require.main === module) {
  const port = Number(process.env.PORT ?? 8080);
  createApp().listen(port, '127.0.0.1', () => {
    process.stdout.write(`intake listening on 127.0.0.1:${port} (store ${databasePath()})\n`);
  });
}
