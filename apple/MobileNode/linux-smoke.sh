#!/usr/bin/env bash
# Run in a fresh user/network namespace with only the loopback interface.
set -euo pipefail
python3 - <<'CHECK'
import fcntl, socket, struct
from pathlib import Path
interfaces = [row.split(":")[0].strip() for row in Path("/proc/net/dev").read_text().splitlines()[2:]]
assert interfaces == ["lo"], "Requires a loopback-only namespace"
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    data = struct.pack("16sH22x", b"lo", 0)
    flags = struct.unpack("16sH22x", fcntl.ioctl(sock, 0x8913, data))[1]
    fcntl.ioctl(sock, 0x8914, struct.pack("16sH22x", b"lo", flags | 1))
CHECK
assets=$(cd "$1" && pwd)
scripts=$(cd "$(dirname "$0")" && pwd)
state=$(mktemp -d)
trap 'if [[ -n ${pid:-} ]]; then kill "$pid" 2>/dev/null || true; fi; rm -rf "$state"' EXIT
cp "$scripts"/{supervisor,gateway-worker,mobile-sharp}.cjs "$assets/"
echo '{"free":true,"omni":true}' > "$state/desired.json"
node "$assets/supervisor.cjs" "$state" "$assets" > "$state/runtime.log" 2>&1 &
pid=$!
node --version
for n in {1..120}; do
    if curl --noproxy '*' -fsS --max-time 4 http://127.0.0.1:3001/api/ping -o "$state/free.json" 2>/dev/null &&
       curl --noproxy '*' -fsS --max-time 4 http://127.0.0.1:20128/api/health/ping -o "$state/omni.json" 2>/dev/null; then
        python3 -c 'import json,sys; assert all(isinstance(json.load(open(f)),dict) for f in sys.argv[1:])' "$state/free.json" "$state/omni.json"
        for port in 3001 20128; do
            curl --noproxy '*' -fLsS --max-time 30 "http://127.0.0.1:$port/" -o "$state/dashboard"
            grep -qi '<html' "$state/dashboard"
        done
        echo 'Both upstream APIs and web dashboards answered in a loopback-only network.'
        exit 0
    fi
    if test -f "$state/state.json" && grep -q '"error:' "$state/state.json"; then cat "$state/state.json"; exit 1; fi
    sleep 1
done
cat "$state/state.json"
for url in http://127.0.0.1:3001/api/ping http://127.0.0.1:20128/api/health/ping; do
  curl --noproxy '*' -sS --max-time 4 -o /dev/null -w '%{url_effective} %{http_code}\n' "$url" || true
done
grep -Ei '⨯|^Error|^ *at |\[error\]|MODULE_NOT_FOUND|Cannot find module|TypeError|ReferenceError|SyntaxError|EACCES|ENOSPC|ERR_UNKNOWN' "$state/runtime.log" | sed -E 's/[[:alnum:]_=-]{24,}/[redacted]/g' | cut -c1-240 | tail -35 || true
exit 1
