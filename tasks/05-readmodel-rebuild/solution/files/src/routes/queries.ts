/**
 * The public read path.
 *
 * Every query is answered by whichever generation the routing key names, and
 * says which one answered it. Callers depend on the response shape, so it is the
 * same whichever generation answers, and a field the answering generation has
 * no column for comes back as null.
 *
 * Generation v2 holds more than v1 does, and the difference is not uniform: the
 * feed carries the delivery's tags, the org bucket knows how many different
 * people it saw, and the tag bucket points at its newest delivery. Each of the
 * three handlers therefore asks for a different shape.
 */

import { Router } from 'express';
import { gel } from '../gel/client.js';
import type { Generation, RouteKey } from '../redis/client.js';
import { servingGeneration } from '../rebuild/durable.js';
import type {
  FeedAnswer, FeedItem, OrgCountAnswer, TagCountAnswer,
} from '../domain/types.js';

export const queriesRouter = Router();

const asIso = (v: unknown): string =>
  v instanceof Date ? v.toISOString() : new Date(String(v)).toISOString();

/**
 * Answers out of whichever generation is serving, and does not hand back an
 * answer taken from a generation that stopped serving while it was being taken.
 *
 * Resolving the routing key and reading the table are two moments, not one. A
 * cutover can land between them, and the generation the reader was told to use
 * is then the one about to be retired: its rows disappear underneath a read
 * that was perfectly correct when it started. So the routing key is read again
 * once the answer is in hand, and an answer collected under a generation that
 * is no longer serving is collected again under the one that is.
 *
 * Routing only ever moves forwards, so this settles after one repeat; the loop
 * is bounded regardless, because a read path is not a place to spin.
 *
 * Which generation is serving is asked of `servingGeneration` rather than of
 * the routing key directly, because a key that is not there is not a key that
 * says v1. The cache can be restarted; the answer to "who is serving" cannot go
 * missing along with it, and after the old generation has been retired the
 * difference is between an answer and an empty table.
 */
async function fromServingGeneration<T>(
  key: RouteKey,
  read: (generation: Generation) => Promise<T>,
): Promise<{ generation: Generation; value: T }> {
  let generation = await servingGeneration(key);
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const value = await read(generation);
    const serving = await servingGeneration(key);
    if (serving === generation) return { generation, value };
    generation = serving;
  }
  return { generation, value: await read(generation) };
}

queriesRouter.get('/feed', async (req, res) => {
  const userId = String(req.query.user_id ?? '');
  const limit = Math.min(Math.max(Number(req.query.limit ?? 20) || 20, 1), 200);
  if (!userId) return res.status(400).json({ error: 'user_id is required' });

  try {
    const { generation, value: rows } = await fromServingGeneration(
      'proj:feed:active',
      (g) => gel.query<{
        seq: number; event_id: string; occurred_at: Date; tags?: string[];
      }>(
        `select ${g === 'v2' ? 'FeedByUserV2' : 'FeedByUserV1'} { seq, event_id, occurred_at${g === 'v2' ? ', tags' : ''} }
         filter .user_id = <str>$user_id
         order by .occurred_at desc then .seq desc
         limit <int64>$limit`,
        { user_id: userId, limit },
      ),
    );

    const items: FeedItem[] = rows.map((r) => ({
      seq: Number(r.seq),
      event_id: r.event_id,
      occurred_at: asIso(r.occurred_at),
      tags: r.tags ? [...r.tags] : [],
    }));
    const body: FeedAnswer = { generation, user_id: userId, items };
    return res.json(body);
  } catch (err) {
    return res.status(500).json({ error: String(err) });
  }
});

queriesRouter.get('/counts/org', async (req, res) => {
  const orgId = String(req.query.org_id ?? '');
  const day = String(req.query.day ?? '');
  if (!orgId || !day) return res.status(400).json({ error: 'org_id and day are required' });

  try {
    const { generation, value: row } = await fromServingGeneration(
      'proj:counts:active',
      (g) => gel.querySingle<{ count: number; actors?: number } | null>(
        `select ${g === 'v2' ? 'CountByOrgV2' : 'CountByOrgV1'} { count${g === 'v2' ? ', actors' : ''} }
         filter .org_id = <str>$org_id and .day_bucket = <str>$day limit 1`,
        { org_id: orgId, day },
      ),
    );
    const body: OrgCountAnswer = {
      generation,
      org_id: orgId,
      day,
      count: row ? Number(row.count) : 0,
      // v1 has no such column; v2 has one and it is zero only when the bucket
      // is. A bucket that is not there at all answers none rather than zero.
      actors: generation === 'v2' ? (row ? Number(row.actors) : 0) : null,
    };
    return res.json(body);
  } catch (err) {
    return res.status(500).json({ error: String(err) });
  }
});

queriesRouter.get('/counts/tag', async (req, res) => {
  const tag = String(req.query.tag ?? '');
  const day = String(req.query.day ?? '');
  if (!tag || !day) return res.status(400).json({ error: 'tag and day are required' });

  try {
    const { generation, value: row } = await fromServingGeneration(
      'proj:tags:active',
      (g) => gel.querySingle<{
        count: number; newest_event_id?: string; newest_at?: Date;
      } | null>(
        `select ${g === 'v2' ? 'RecentByTagV2' : 'RecentByTagV1'} { count${g === 'v2' ? ', newest_event_id, newest_at' : ''} }
         filter .tag = <str>$tag and .day_bucket = <str>$day limit 1`,
        { tag, day },
      ),
    );
    const body: TagCountAnswer = {
      generation,
      tag,
      day,
      count: row ? Number(row.count) : 0,
      newest_event_id: row?.newest_event_id ?? null,
      newest_at: row?.newest_at === undefined ? null : asIso(row.newest_at),
    };
    return res.json(body);
  } catch (err) {
    return res.status(500).json({ error: String(err) });
  }
});
