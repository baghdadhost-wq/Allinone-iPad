#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
out=${1:?output directory required}
mkdir -p "$out"
out=$(cd "$out" && pwd)
cd "$work"
fetch() {
  curl -fLsS --retry 3 "$1" -o archive.tgz
  echo "$2  archive.tgz" | shasum -a 256 -c -
  mkdir "$3"; tar xzf archive.tgz -C "$3" --strip-components=1
}
fetch https://registry.npmjs.org/omniroute/-/omniroute-3.8.54.tgz 19b91105c0bdcc829b123b693e44abf754683d680183c1265a9af6c981f97de5 omni
fetch https://codeload.github.com/tashfeenahmed/freellmapi/tar.gz/refs/tags/v0.16.39 0158a2cbdacef6cf75a400089837bd19275f62e19d6f4f37a0860e971682a229 free
mkdir -p payload/omni payload/free/server payload/free/client
cp -R omni/dist/. payload/omni/
cp omni/LICENSE omni/THIRD_PARTY_NOTICES.md payload/omni/
cp free/LICENSE payload/free/
# Next's standalone HTTP server uses its own directory as cwd. The embedded
# supervisor already sets that directory before creating the worker.
python3 - <<'PY'
from pathlib import Path
p=Path('payload/omni/server.js')
s=p.read_text()
assert s.count('process.chdir(__dirname)')==1
p.write_text(s.replace('process.chdir(__dirname)', ''))
p=Path('free/server/src/db/index.ts')
s=p.read_text()
needle="platform === 'android' ? nodeSqliteFactory : betterSqliteFactory"
assert s.count(needle)==1
p.write_text(s.replace(needle,'nodeSqliteFactory'))
PY
(cd free && npm ci --no-audit --no-fund && npm run build -w server && npm run build -w client)
cp -R free/server/dist payload/free/server/
cp -R free/client/dist payload/free/client/
cp free/server/package.json payload/free/server/
# Install JS runtime dependencies independently of the desktop tools.
node - <<'JS'
const fs=require('node:fs');
for(const [dest,src] of [['payload/free','free/server/package.json'],['payload/omni','omni/dist/package.json']]){
 const obj=JSON.parse(fs.readFileSync(src));
 const deps={...obj.dependencies};
 delete deps['@freellmapi/shared'];
 fs.writeFileSync(dest+'/package.json',JSON.stringify({name:'apple-gateway',private:true,dependencies:deps}));
}
JS
(cd payload/omni && npm install --omit=optional --ignore-scripts --legacy-peer-deps --no-audit --no-fund)
(cd payload/free && npm install --omit=optional --ignore-scripts --no-audit --no-fund)
python3 "$here/pack.py" payload "$out/gateways.dat"
