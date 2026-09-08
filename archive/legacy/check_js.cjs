/* Syntax checks for static scripts, extension scripts and inline application JS. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
let count = 0;
for (const directory of ['static', 'espn-extension']) {
  for (const name of fs.readdirSync(path.join(__dirname, directory))) {
    if (!name.endsWith('.js')) continue;
    const filename = path.join(directory, name);
    new vm.Script(fs.readFileSync(path.join(__dirname, filename), 'utf8'), {filename});
    count++;
  }
}
const html = fs.readFileSync(path.join(__dirname, 'templates/index.html'), 'utf8');
for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
  if (!match[1].trim()) continue;
  new vm.Script(match[1], {filename:'templates/index.html inline script'});
  count++;
}
console.log(`PASS: syntax for ${count} JavaScript scripts`);
