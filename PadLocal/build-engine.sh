#!/usr/bin/env bash
set -eu
revision=43f31f400c66dd44ce52a044119db77c271fed06
root=$(pwd)
temp=$(mktemp -d)
trap 'rm -rf "$temp"' EXIT
git -C "$temp" init -q
git -C "$temp" fetch --depth 1 https://github.com/PrismML-Eng/llama.cpp.git "$revision"
git -C "$temp" checkout -q --detach FETCH_HEAD
(cd "$temp" && bash build-xcframework.sh ios-device)
mkdir -p "$root/Vendor"
cp -R "$temp/build-apple/llama.xcframework" "$root/Vendor/"
cp "$temp/LICENSE" "$root/Vendor/Engine-LICENSE.txt"
