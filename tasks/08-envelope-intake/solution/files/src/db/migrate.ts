import fs from 'node:fs';
import path from 'node:path';

import { adoptHistory } from './adopt';
import { close, databasePath, exec } from './client';

/**
 * Applies `schema.sql`, then every `.sql` file in `migrations/` in name order,
 * then brings whatever the store already held into the tables routing uses.
 * Idempotent: every statement is guarded, so running it twice is a no-op.
 *
 * The adoption is here rather than in a `.sql` file because a conversation is
 * named by a hash of its root identifier and the derivation lives in
 * `src/intake/threading.ts`. Doing it anywhere else would be a second way of
 * grouping deliveries into conversations, which that module says there is not.
 */
export async function migrate(): Promise<string[]> {
  const applied: string[] = [];
  const here = __dirname;

  await exec(fs.readFileSync(path.join(here, 'schema.sql'), 'utf8'));
  applied.push('schema.sql');

  const migrations = path.join(here, 'migrations');
  if (fs.existsSync(migrations)) {
    for (const name of fs.readdirSync(migrations).sort()) {
      if (!name.endsWith('.sql')) continue;
      await exec(fs.readFileSync(path.join(migrations, name), 'utf8'));
      applied.push(name);
    }
  }

  const adopted = await adoptHistory();
  if (adopted > 0) applied.push(`adopted ${adopted} existing tickets`);

  return applied;
}

if (require.main === module) {
  migrate()
    .then(async (applied) => {
      process.stdout.write(`intake store at ${databasePath()}: ${applied.join(', ')}\n`);
      await close();
    })
    .catch(async (error: unknown) => {
      process.stderr.write(`migrate failed: ${String(error)}\n`);
      await close();
      process.exit(1);
    });
}
