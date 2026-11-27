#!/usr/bin/env bash
set -euo pipefail
rev=43f31f400c66dd44ce52a044119db77c271fed06
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git -C "$tmp" init -q
git -C "$tmp" fetch --depth 1 https://github.com/PrismML-Eng/llama.cpp.git "$rev"
git -C "$tmp" checkout -q --detach FETCH_HEAD
cmake -S "$tmp" -B "$tmp/out" -DCMAKE_BUILD_TYPE=Release -DGGML_METAL=OFF -DBUILD_SHARED_LIBS=ON -DLLAMA_BUILD_COMMON=OFF -DLLAMA_BUILD_TOOLS=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF
cmake --build "$tmp/out" --target llama -j 3
mkdir "$tmp/headers"
ln -s "$tmp/include" "$tmp/headers/llama"
lib=$(find "$tmp/out" -name libllama.dylib -print -quit)
xcrun clang++ -std=c++17 -fobjc-arc -I"$tmp/headers" -I"$tmp/ggml/include" Sources/Engine.mm Tests/respond.mm -framework Foundation "$lib" -Wl,-rpath,"$(dirname "$lib")" -o "$tmp/respond"
python3 - <<'PY' > "$tmp/urls"
import json,re,urllib.request
from pathlib import Path
for repo,f in re.findall(r'Entry\(name:"[^"]+",repo:"([^"]+)",file:"([^"]+)"',Path('Sources/PadLocal.swift').read_text()):
    with urllib.request.urlopen('https://huggingface.co/api/models/'+repo+'?blobs=true',timeout=60) as r: c=json.load(r)
    b=next(s['lfs'] for s in c['siblings'] if s['rfilename']==f)
    print('https://huggingface.co/'+repo+'/resolve/'+c['sha']+'/'+f,b['sha256'],f)
PY
while read -r url sha name; do
    curl --retry 3 -fsSL "$url" -o "$tmp/test.gguf"
    echo "$sha  $tmp/test.gguf" | shasum -a 256 -c -
    echo "Testing $name"
    "$tmp/respond" "$tmp/test.gguf"
    rm "$tmp/test.gguf"
done < "$tmp/urls"
