"""Check public download metadata and the GGUF signature without downloading the weights."""
import json
import re
import urllib.request
from pathlib import Path

source = Path("Sources/PadLocal.swift").read_text()
entries = re.findall(r'Entry\(name:"[^"]+",repo:"([^"]+)",file:"([^"]+)"', source)
assert len(entries) == 3
for repo, filename in entries:
    with urllib.request.urlopen(f"https://huggingface.co/api/models/{repo}?blobs=true",timeout=60) as response:
        card = json.load(response)
    blob = next(s["lfs"] for s in card["siblings"] if s["rfilename"] == filename)
    assert blob["size"] > 1_000_000_000 and re.fullmatch("[a-f0-9]{64}",blob["sha256"])
    url = f"https://huggingface.co/{repo}/resolve/{card['sha']}/{filename}"
    request = urllib.request.Request(url,headers={"Range":"bytes=0-3"})
    with urllib.request.urlopen(request,timeout=60) as response:
        assert response.read(4) == b"GGUF"
    print(repo, filename, blob["size"], flush=True)
