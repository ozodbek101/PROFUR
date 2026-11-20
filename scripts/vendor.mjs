// Copies third-party browser assets from node_modules into static/ so the app
// never depends on a CDN (workshop internet is unreliable). Run: npm run vendor
import { copyFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const out = (...p) => join(root, "static", ...p);
mkdirSync(out("vendor"), { recursive: true });
mkdirSync(out("fonts"), { recursive: true });

copyFileSync(join(root, "node_modules/alpinejs/dist/cdn.min.js"), out("vendor", "alpine.min.js"));

for (const subset of ["latin", "latin-ext"]) {
  for (const weight of [400, 500, 600, 700]) {
    const name = `dm-sans-${subset}-${weight}-normal.woff2`;
    copyFileSync(join(root, "node_modules/@fontsource/dm-sans/files", name), out("fonts", name));
  }
}
// DM Sans has no Cyrillic glyphs; Inter's Cyrillic subset is served under the
// same family name (see the unicode-range rules in frontend/app.css).
for (const weight of [400, 500, 600, 700]) {
  const name = `inter-cyrillic-${weight}-normal.woff2`;
  copyFileSync(join(root, "node_modules/@fontsource/inter/files", name), out("fonts", name));
}
console.log("Vendored Alpine.js, DM Sans and Inter Cyrillic into static/");
