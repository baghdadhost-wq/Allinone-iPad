import gzip
import os
import shutil
import struct
import sys
from pathlib import Path

root = Path(sys.argv[1])
with gzip.open(sys.argv[2], "wb", compresslevel=3) as dst:
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {".git", ".bin"} and not (Path(folder)/d).is_symlink())
        for name in sorted(names):
            path = Path(folder) / name
            if path.is_symlink() or path.suffix in {".node", ".dylib", ".so", ".dll", ".exe", ".map", ".a"}:
                continue
            key = path.relative_to(root).as_posix().encode()
            dst.write(struct.pack(">II", len(key), path.stat().st_size))
            dst.write(key)
            with path.open("rb") as src:
                shutil.copyfileobj(src, dst)
    dst.write(bytes(8))
