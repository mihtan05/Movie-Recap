import * as esbuild from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.resolve(__dirname, '..', 'mcp_server', 'ui_dist');
fs.mkdirSync(outDir, { recursive: true });

const result = await esbuild.build({
  entryPoints: [path.join(__dirname, 'app.js')],
  bundle: true,
  format: 'esm',
  minify: true,
  write: false,
  target: ['es2022'],
});

const jsCode = result.outputFiles[0].text;
const template = fs.readFileSync(path.join(__dirname, 'template.html'), 'utf8');
const finalHtml = template.replace(
  '<script type="module" id="app-bundle-placeholder"></script>',
  () => `<script type="module">\n${jsCode}\n</script>`
);

const outPath = path.join(outDir, 'app.html');
fs.writeFileSync(outPath, finalHtml, 'utf8');
console.log(`Bundled single-file MCP App HTML -> ${outPath} (${(Buffer.byteLength(finalHtml) / 1024).toFixed(1)} KB)`);
