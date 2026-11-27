// Node.js 20+ desktop client for the native Allinone iPad host.
import { randomUUID } from 'node:crypto';
import tls from 'node:tls';
import { isIPv4 } from 'node:net';
import { createInterface } from 'node:readline/promises';
import { Writable } from 'node:stream';
import { stdin, stdout } from 'node:process';

const address = process.argv[2] ?? '';
const [ip, rawPort = '8744', extra] = address.split(':');
const port = Number(rawPort);
if (!isIPv4(ip) || !Number.isInteger(port) || port < 1 || port > 65535 || extra !== undefined) {
  console.error('Usage: node desktop/client.mjs 192.168.1.25:8744');
  process.exit(2);
}
const hidden = new Writable({ write(_chunk, _encoding, done) { done(); } });
stdout.write('Pairing code: ');
const secretInput = createInterface({ input: stdin, output: hidden, terminal: stdin.isTTY });
const code = (await secretInput.question('')).trim();
secretInput.close();
stdout.write('\n');
const key = Buffer.from(code, 'base64');
if (key.length !== 32 || key.toString('base64') !== code) throw new Error('Invalid pairing code');

let session = randomUUID();
async function ask(question) {
  const body = Buffer.from(JSON.stringify({ question, session }));
  if (body.length > 1048576) throw new Error('Question too long');
  const header = Buffer.alloc(4);
  header.writeUInt32BE(body.length);
  // PSK-only cipher authenticates both peers using the secret from the iPad.
  const conn = tls.connect({host: ip, port, minVersion: 'TLSv1.2', maxVersion: 'TLSv1.2',
    ciphers: 'PSK-AES128-GCM-SHA256', rejectUnauthorized: false,
    pskCallback: () => ({ psk: key, identity: 'allinone-v1' })});
  const deadline = setTimeout(() => conn.destroy(new Error('Host timed out')), 310000);
  conn.once('secureConnect', () => conn.write(Buffer.concat([header, body])));
  const chunks = [];
  let total = 0;
  let length;
  try {
    for await (const chunk of conn) {
      chunks.push(chunk);
      total += chunk.length;
      if (length === undefined && total >= 4) {
        length = Buffer.concat(chunks, total).readUInt32BE();
        if (!length || length > 1048576) throw new Error('Invalid reply size');
      }
      if (length !== undefined && total >= length + 4) {
        const reply = JSON.parse(Buffer.concat(chunks, total).subarray(4, 4 + length).toString('utf8'));
        if (typeof reply.answer === 'string') return reply.answer;
        throw new Error(reply.error ?? 'Invalid reply');
      }
    }
    throw new Error('Connection closed before the answer');
  } finally { clearTimeout(deadline); conn.destroy(); }
}
const cli = createInterface({ input: stdin, output: stdout });
try {
  for (;;) {
    const question = (await cli.question('Question (/new or /quit): ')).trim();
    if (question === '/quit') break;
    if (question === '/new') { session = randomUUID(); continue; }
    if (!question) continue;
    try { console.log(await ask(question)); } catch (error) { console.error(error.message); }
  }
} finally { cli.close(); }
