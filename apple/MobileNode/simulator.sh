#!/usr/bin/env bash
set -euo pipefail
device=$(xcrun simctl list devices available --json | python3 -c 'import json,sys; d=json.load(sys.stdin)["devices"];print(next(v["udid"] for k,vs in sorted(d.items(),reverse=True) if ".iOS-" in k for v in vs if v["name"].startswith("iPhone")))')
xcrun simctl boot "$device" || xcrun simctl list devices booted | grep -F "$device"
xcrun simctl bootstatus "$device" -b
xcodebuild -quiet -project apple/Allinone.xcodeproj -scheme Allinone -configuration Release -destination "id=$device" -derivedDataPath build-sim build
app=build-sim/Build/Products/Release-iphonesimulator/Allinone.app
id=app.baghdadhost.allinone
xcrun simctl install "$device" "$app"
SIMCTL_CHILD_ALLINONE_OFFLINE_TEST=1 xcrun simctl launch --stderr=/tmp/gateway-simulator.log "$device" "$id" --test-mobile-gateways
data=$(xcrun simctl get_app_container "$device" "$id" data)
state="$data/Library/Application Support/MobileGateways/state.json"
for n in {1..120}; do
  if curl --max-time 4 -fsS http://127.0.0.1:3001/api/ping -o /tmp/free-ping && curl --max-time 5 -fsS http://127.0.0.1:20128/api/health/ping -o /tmp/omni-ping; then
    python3 -c 'import json; [json.load(open(p)) for p in ("/tmp/free-ping","/tmp/omni-ping")]'
    echo "FreeLLMAPI and OmniRoute returned JSON from the iOS simulator."
    exit 0
  fi
  if test -f "$state"; then cat "$state"; if grep -q '"error:' "$state"; then break; fi; fi
  sleep 2
done
# Print selected errors only. Upstream first-run setup codes do not belong in logs.
grep -Ei 'cannot find|module not found|ERR_MODULE|fatal error|symbol not found|library not loaded' /tmp/gateway-simulator.log | head -20 || true
exit 1
