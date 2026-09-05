/**
 * Verifier plumbing.
 *
 * Everything here reaches the stores through system binaries (/usr/bin/gel,
 * redis-cli) and the service through HTTP. Nothing is imported from the
 * workspace, so a solver cannot change what the verifier sees by changing their
 * own code, and no helper is shared between the thing being graded and the
 * thing grading it.
 */

import { spawn, spawnSync } from 'node:child_process';
import { openSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';

export const WORKSPACE = process.env.WORKSPACE ?? '/app/event-feed';
export const GEL_DSN = process.env.GEL_DSN ?? 'gel://admin:dev@localhost:5656/main';
export const BASE_URL = process.env.BASE_URL ?? 'http://127.0.0.1:8080';
export const VERIFIER = process.env.VERIFIER_DIR ?? '/opt/verifier';

export { delay };

// ------------------------------------------------------------------- Gel ---

const GEL_ARGS = ['query', '-F', 'json', '--tls-security', 'insecure', '--dsn', GEL_DSN];

export function gelQuery(statement) {
  const out = spawnSync('/usr/bin/gel', [...GEL_ARGS, statement], {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  if (out.status !== 0) {
    throw new Error(`gel query failed: ${(out.stderr || out.stdout || '').slice(0, 400)}`);
  }
  // `-F json` renders one pretty-printed array per statement, so the whole of
  // stdout is the result of a single statement.
  const text = out.stdout.trim();
  if (!text) return [];
  return JSON.parse(text);
}

export function gelScript(script) {
  const out = spawnSync('/usr/bin/gel', [...GEL_ARGS, '-f', '-'], {
    input: script,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  if (out.status !== 0) {
    throw new Error(`gel script failed: ${(out.stderr || out.stdout || '').slice(0, 400)}`);
  }
  return out.stdout;
}

export function gelReady(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const out = spawnSync('/usr/bin/gel', [...GEL_ARGS, 'select 1'], { encoding: 'utf8' });
    if (out.status === 0) return true;
    spawnSync('sleep', ['1']);
  }
  return false;
}

/** Gel renders instants as +00:00; the model and the service both use Z. */
export const isoInstant = (value) => new Date(value).toISOString();

// ----------------------------------------------------------------- Redis ---

export function redisCli(...args) {
  const out = spawnSync('redis-cli', args, { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
  if (out.status !== 0) throw new Error(`redis-cli failed: ${out.stderr}`);
  return out.stdout.trim();
}

export const redisGet = (key) => {
  const v = redisCli('get', key);
  return v === '' ? null : v;
};
export const redisSet = (key, value) => redisCli('set', key, String(value));
export const redisDel = (key) => redisCli('del', key);

export const ROUTE_KEYS = ['proj:feed:active', 'proj:counts:active', 'proj:tags:active'];

export function routingState() {
  const values = ROUTE_KEYS.map((k) => redisGet(k) ?? 'v1');
  return {
    values,
    generations: [...new Set(values)],
    torn: new Set(values).size > 1,
    allV2: values.every((v) => v === 'v2'),
    allV1: values.every((v) => v !== 'v2'),
  };
}

/** This process's own arrival number, which is what a fault is armed against. */
export const checkpointArrivals = (name) => Number(redisGet(`test:cp:${name}`) ?? 0);

/**
 * Arrivals ever. Callers that reach a checkpoint at the same moment overwrite
 * each other's answer in `test:cp`, so counting how many are parked has to come
 * from the tally instead.
 */
export const checkpointTally = (name) => Number(redisGet(`test:cpn:${name}`) ?? 0);
export const holdCheckpoint = (name) => redisSet(`test:hold:${name}`, '1');
export const releaseCheckpoint = (name) => redisDel(`test:hold:${name}`);
export const killAtCheckpoint = (name, nth) => redisSet(`test:fault:${name}`, String(nth));
export const disarmCheckpoint = (name) => redisDel(`test:fault:${name}`);

/**
 * A live record of what was sent to Redis, independent of any client library
 * the solver chose. Used to decide whether routing moved atomically.
 */
export function startMonitor() {
  const proc = spawn('redis-cli', ['monitor'], { stdio: ['ignore', 'pipe', 'ignore'] });
  const lines = [];
  proc.stdout.on('data', (chunk) => {
    for (const line of String(chunk).split('\n')) if (line.trim()) lines.push(line.trim());
  });
  return {
    lines,
    stop() {
      try { proc.kill('SIGKILL'); } catch { /* already gone */ }
    },
  };
}

// ------------------------------------------------------------------ HTTP ---

export async function http(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 120_000);
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: options.method ?? 'GET',
      headers: options.body ? { 'content-type': 'application/json' } : undefined,
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
    const text = await res.text();
    let body = null;
    try { body = JSON.parse(text); } catch { body = { raw: text.slice(0, 400) }; }
    return { status: res.status, body };
  } catch (err) {
    return { status: 0, body: null, error: String(err) };
  } finally {
    clearTimeout(timer);
  }
}

// ------------------------------------------------------- app lifecycle -----

let child = null;
let exited = false;
// Which launch the `exited` flag is about. A killed process's exit event can
// land after the replacement has been spawned, and without this the harness
// reads the corpse's death as the new process failing to start -- a restart
// that worked, graded as a harness failure.
let launch = 0;

export function appPid() {
  return child?.pid ?? null;
}

export function startApp(logPath) {
  const fd = openSync(logPath, 'a');
  const mine = ++launch;
  exited = false;
  child = spawn('npm', ['start'], {
    cwd: WORKSPACE,
    detached: true,
    stdio: ['ignore', fd, fd],
    env: {
      PATH: '/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin',
      HOME: '/root',
      NODE_ENV: 'production',
      IS_TEST: 'true',
      GEL_DSN,
      REDIS_URL: 'redis://127.0.0.1:6379',
      PORT: '8080',
      GEL_READY_TIMEOUT_MS: '300000',
    },
  });
  child.on('error', () => {});
  child.on('exit', () => { if (mine === launch) exited = true; });
  return child.pid;
}

export function stopApp() {
  if (!child) return;
  launch += 1;
  try { process.kill(-child.pid, 'SIGKILL'); } catch { /* already gone */ }
  child = null;
}

/**
 * Waits for the service this grader started, and for no other.
 *
 * Something answering on the port is not the same fact as the service being up,
 * and the difference is the whole run: a process left behind by the solver will
 * answer /healthz perfectly well while the child we spawned is dead of
 * EADDRINUSE, and everything after this -- the checkpoints, the pid the crash
 * is delivered to, the state the rules are read from -- would then be about a
 * process we neither started nor can reason about. test.sh clears the port
 * before grading; this is what makes a failure to clear it visible instead of
 * silently changing what was measured.
 */
export async function waitForApp(timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await http('/healthz', { timeoutMs: 3_000 });
    if (res.status === 200) {
      if (exited) return 'foreign';
      return true;
    }
    if (exited) return false;
    await delay(200);
  }
  return false;
}

/**
 * The launched process exiting is the definitive signal; the port is a
 * secondary one, in case a candidate daemonises itself away from us.
 */
export async function appIsDown(timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (exited) return true;
    const res = await http('/healthz', { timeoutMs: 1_500 });
    if (res.status !== 200) return true;
    await delay(100);
  }
  return false;
}

export const appExited = () => exited;
