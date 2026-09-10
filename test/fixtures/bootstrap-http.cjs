const http = require('node:http');
const fs = require('node:fs');
const root = process.env.MM_BOOTSTRAP_HTTP_ROOT;
const ready = process.env.MM_BOOTSTRAP_HTTP_READY;
if (root && ready) {
  const server = http.createServer((req, res) => {
    if (req.url === '/bundle.zip') {
      res.writeHead(302, { location: '/asset.zip' }); res.end(); return;
    }
    if (req.url !== '/asset.zip') { res.writeHead(404); res.end(); return; }
    const body = fs.readFileSync(root + '/asset.zip');
    res.writeHead(200, { 'content-type': 'application/octet-stream', 'content-length': body.length });
    res.end(body);
  });
  server.listen(0, '127.0.0.1', () => {
    fs.writeFileSync(ready, JSON.stringify({ url: `http://127.0.0.1:${server.address().port}/bundle.zip` }));
  });
}
