// Local development coordinator for macOS/Linux. Each project owns its startup.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const root = fileURLToPath(new URL('../', import.meta.url));
const entries = {
  frontend: { command: 'npm', args: ['run', 'dev'], cwd: `${root}frontend` },
  backend: { command: './dev.sh', args: [], cwd: `${root}backend` },
};
const target = process.argv[2] || 'all';
if (process.argv.length > 3 || !['all', 'frontend', 'backend'].includes(target)) {
  console.error('Usage: ./dev.sh [all|frontend|backend]');
  process.exit(1);
}

const children = [];
let stopping;
function signalGroup(child, signal) {
  if (!child.pid) return false;
  try { process.kill(-child.pid, signal); return true; }
  catch (error) { if (error.code !== 'ESRCH') throw error; return false; }
}
function stop() {
  return stopping ||= (async () => {
    for (const child of children) signalGroup(child, 'SIGTERM');
    const deadline = Date.now() + 5000;
    while (children.some(child => signalGroup(child, 0)) && Date.now() < deadline) await delay(50);
    for (const child of children) signalGroup(child, 'SIGKILL');
    await Promise.all(children.map(child => child.done));
  })();
}
for (const [signal, code] of [['SIGINT', 130], ['SIGTERM', 143]]) {
  process.on(signal, () => { process.exitCode = code; void stop(); });
}

try {
  for (const name of target === 'all' ? ['backend', 'frontend'] : [target]) {
    const { command, args, cwd } = entries[name];
    const child = spawn(command, args, { cwd, stdio: 'inherit', detached: true });
    child.done = new Promise(resolve => {
      child.once('error', error => resolve({ error }));
      child.once('exit', (code, signal) => resolve({ code, signal }));
    });
    children.push(child);
  }
  console.log('Press Ctrl+C to stop the selected services.');
  const result = await Promise.race(children.map(child => child.done));
  if (!stopping) {
    console.error(result.error?.message || `A service exited (${result.signal || result.code}); stopping the selected services.`);
    process.exitCode = result.code || 1;
  }
} finally {
  await stop();
}
