import { mkdir, readFile, writeFile } from 'node:fs/promises';

await mkdir(new URL('../dist/server/', import.meta.url), { recursive: true });
let html = await readFile(new URL('../dist/index.html', import.meta.url), 'utf8');
const stylesheet = html.match(/<link rel="stylesheet" crossorigin href="([^"]+)">/);
const moduleScript = html.match(/<script type="module" crossorigin src="([^"]+)"><\/script>/);
if (!stylesheet || !moduleScript) throw new Error('Vite asset tags were not found');
const css = await readFile(new URL(`../dist${stylesheet[1]}`, import.meta.url), 'utf8');
const javascript = await readFile(new URL(`../dist${moduleScript[1]}`, import.meta.url), 'utf8');
html = html
  .replace(stylesheet[0], () => `<style>${css}</style>`)
  .replace(moduleScript[0], () => `<script type="module">${javascript.replaceAll('</script>', '<\\/script>')}</script>`);
await writeFile(
  new URL('../dist/server/index.js', import.meta.url),
  `const html = ${JSON.stringify(html)};
const apiOrigin = 'https://eop-peach.vercel.app';
export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/') || url.pathname === '/healthz') {
      const upstream = new URL(url.pathname + url.search, apiOrigin);
      const headers = new Headers(request.headers);
      headers.delete('host');
      return fetch(new Request(upstream, {
        method: request.method,
        headers,
        body: request.method === 'GET' || request.method === 'HEAD' ? undefined : request.body,
        redirect: 'manual'
      }));
    }
    if (request.method !== 'GET') return new Response('Method not allowed', {status: 405});
    return new Response(html, {headers: {'content-type': 'text/html; charset=utf-8'}});
  }
};\n`,
  'utf8',
);
