#!/usr/bin/env bash
set -euo pipefail
device=$(xcrun simctl list devices available --json | python3 -c 'import json,sys; d=json.load(sys.stdin)["devices"];print(next(v["udid"] for k,vs in sorted(d.items(),reverse=True) if ".iOS-" in k for v in vs if v["name"].startswith("iPhone")))')
xcrun simctl boot "$device" || xcrun simctl list devices booted | grep -F "$device"
xcrun simctl bootstatus "$device" -b
xcodebuild -quiet -project apple/Allinone.xcodeproj -scheme Allinone -configuration Release -destination "id=$device" -derivedDataPath build-sim ARCHS=arm64 ONLY_ACTIVE_ARCH=YES build
app=build-sim/Build/Products/Release-iphonesimulator/Allinone.app
id=app.baghdadhost.allinone
xcrun simctl install "$device" "$app"
python3 - <<'PYTHON' &
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
class Fixture(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path != '/v1/chat/completions' or body['messages'][-1]['content'] != 'ui-bridge-question':
            self.send_error(400)
            return
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(b'{"choices":[{"message":{"content":"ui-bridge-ok"}}]}')
HTTPServer(('127.0.0.1',18761),Fixture).serve_forever()
PYTHON
fixture_pid=$!
trap 'kill "$fixture_pid" 2>/dev/null || true' EXIT
SIMCTL_CHILD_ALLINONE_OFFLINE_TEST=1 xcrun simctl launch --stderr=/tmp/gateway-simulator.log "$device" "$id" --test-mobile-gateways
data=$(xcrun simctl get_app_container "$device" "$id" data)
state="$data/Library/Application Support/MobileGateways/state.json"
for n in {1..120}; do
  if test -f "$data/Documents/original-ui-passed" && curl --max-time 4 -fsS http://127.0.0.1:3001/api/ping -o /tmp/free-ping && curl --max-time 5 -fsS http://127.0.0.1:20128/api/health/ping -o /tmp/omni-ping; then
    python3 -c 'import json; [json.load(open(p)) for p in ("/tmp/free-ping","/tmp/omni-ping")]'
    echo "Original UI sent and displayed the fixture answer. FreeLLMAPI and OmniRoute returned JSON from the iOS simulator."
    xcrun simctl terminate "$device" "$id"
    mkdir -p "$data/Documents/Workspace/Empty Project"
    xcodebuild -project apple/Allinone.xcodeproj -scheme Allinone -configuration Release -destination "id=$device" -derivedDataPath build-sim ARCHS=arm64 ONLY_ACTIVE_ARCH=YES -parallel-testing-enabled NO -only-testing:FolderUITests -resultBundlePath /tmp/FolderCheck.xcresult test || {
      xcrun xcresulttool get test-results summary --path /tmp/FolderCheck.xcresult
      exit 1
    }
    exit 0
  fi
  if test -f "$state"; then cat "$state"; if grep -q '"error:' "$state"; then break; fi; fi
  sleep 2
done
# Print selected errors only. Upstream first-run setup codes do not belong in logs.
grep -Ei 'cannot find|module not found|ERR_MODULE|fatal error|symbol not found|library not loaded' /tmp/gateway-simulator.log | head -20 || true
exit 1
