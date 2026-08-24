"""Pull a single file off a Beam volume.

    python pull_one.py vicecoast-meshes/_error_run.txt

Must be a real file, not piped via stdin: beam's multipart transfer spawns
worker processes that re-import __main__, and '<stdin>' is not a path.
Also patches RemotePath.path, which uses os.path.join and therefore emits
backslashes on Windows, making the gateway read the whole thing as a volume name.
"""
import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")

import beta9.multipart as mp


def _posix_path(self):
    if self.volume_path == "":
        return self.volume_name + "/"
    return f"{self.volume_name}/{self.volume_path}".replace("\\", "/").replace("//", "/")


mp.RemotePath.path = property(_posix_path)

from beam.cli import main  # noqa: E402

if __name__ == "__main__":
    remote = sys.argv[1]
    dest = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(remote)
    sys.argv = ["beam", "cp", f"beam://{remote}", os.path.abspath(dest)]
    try:
        main.cli()
    except SystemExit:
        pass
