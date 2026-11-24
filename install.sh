#!/usr/bin/env sh
# Allinone installer for macOS / Linux:  ./install.sh
# Checks Python 3.10+ and Git, then runs `python3 allinone.py install`, which downloads a
# portable Node.js, OmniRoute, FreeLLMAPI and Claude Code into ./runtime
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    PY="$c"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10+ is required."
  echo "  macOS:  brew install python      Debian/Ubuntu:  sudo apt install python3"
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Git is required."
  echo "  macOS:  xcode-select --install   Debian/Ubuntu:  sudo apt install git"
  exit 1
fi

chmod +x "$ROOT/allinone" 2>/dev/null || true
"$PY" "$ROOT/allinone.py" install "$@"

echo
echo "Start it with:  $ROOT/allinone"
echo "Tip: make it available everywhere:  ln -sf \"$ROOT/allinone\" ~/.local/bin/allinone"
