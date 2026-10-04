// Run inside the actual ARC runner image, with its pod's Docker socket.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const os = require('node:os');
const fs = require('node:fs');

const run = (command, args) => execFileSync(command, args, {
  encoding: 'utf8', timeout: 120_000, stdio: ['ignore', 'pipe', 'pipe'],
}).trim();

const cpus = os.cpus().length;
const memory = os.totalmem();
console.log(JSON.stringify({ cpus, memory, kernel: os.release() }));
assert.equal(cpus, 4, 'guest must expose four CPUs, not the Kubernetes node');
assert.equal(Number(run('getconf', ['_NPROCESSORS_ONLN'])), 4);
assert(memory > 8 * 1024 ** 3 && memory < 9 * 1024 ** 3,
  'guest memory must be eight GiB plus bounded guest overhead');

const store = '/home/runner/.pnpm-store-shared';
const marker = `${store}/kata-smoke-${process.pid}`;
try {
  fs.writeFileSync(marker, 'guest writes reach the shared cache\n', { flag: 'wx' });
  assert.equal(fs.readFileSync(marker, 'utf8'), 'guest writes reach the shared cache\n');
} finally {
  if (fs.existsSync(marker)) fs.unlinkSync(marker);
}

const docker = JSON.parse(run('docker', ['info', '--format', '{{json .}}']));
assert.equal(docker.NCPU, 4);
assert(docker.MemTotal < 9 * 1024 ** 3);
assert(docker.RegistryConfig.Mirrors.includes('http://192.168.122.1:5000/'));
// Pull, networking, service startup, and a filesystem write in a nested container.
assert.equal(run('docker', ['run', '--rm', 'alpine:3.22', 'sh', '-ec',
  'echo test >/tmp/test; test "$(cat /tmp/test)" = test; wget -qO /dev/null https://github.com']), '');
const tag = `kata-smoke-${process.pid}:test`;
const service = `kata-smoke-${process.pid}`;
try {
  execFileSync('docker', ['build', '--tag', tag, '-'], {
    input: 'FROM alpine:3.22\nRUN echo built > /build-check\n',
    encoding: 'utf8', timeout: 120_000, stdio: ['pipe', 'pipe', 'pipe'],
  });
  assert.equal(run('docker', ['run', '--rm', tag, 'cat', '/build-check']), 'built');
  run('docker', ['run', '--detach', '--name', service,
    '--publish', '127.0.0.1::8080', tag, 'sh', '-ec',
    'mkdir /www; echo ready >/www/index.html; busybox httpd -f -p 8080 -h /www']);
  const address = run('docker', ['port', service, '8080/tcp']);
  assert.equal(run('curl', ['--fail', '--silent', '--show-error',
    '--retry', '5', '--retry-connrefused', '--retry-delay', '1', `http://${address}/`]), 'ready');
} finally {
  // Only resources created by this smoke test; never prune the daemon.
  try { run('docker', ['rm', '--force', service]); } catch {}
  try { run('docker', ['image', 'rm', tag]); } catch {}
}
console.log('Kata resource visibility, shared storage, and nested Docker smoke passed');
