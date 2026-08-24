"""
Shrink radio tracks for the web.

A 6MB MP3 is a 6MB download before the station can play, and game music does
not need album-master bitrates - it sits under an engine, tyre noise and a
siren. Re-encoding to a sane bitrate typically cuts 60-80% with no audible
difference in context.

    python pipeline/optimize_music.py            # whole music/ folder
    python pipeline/optimize_music.py --bitrate 96 --mono

Needs ffmpeg on PATH. Originals are moved to music_original/ - nothing is
deleted, so you can re-run with different settings.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
MUSIC = os.path.join(ROOT, "music")
BACKUP = os.path.join(ROOT, "music_original")
EXT = {".mp3", ".ogg", ".m4a", ".wav", ".flac", ".opus", ".aac", ".webm"}


def have_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def main():
    if not have_ffmpeg():
        sys.exit("ffmpeg not found on PATH - install it, then re-run.")

    bitrate = "112"
    mono = False
    if "--bitrate" in sys.argv:
        bitrate = sys.argv[sys.argv.index("--bitrate") + 1]
    if "--mono" in sys.argv:
        mono = True

    jobs = []
    for dirpath, _dirs, files in os.walk(MUSIC):
        for n in sorted(files):
            if os.path.splitext(n)[1].lower() in EXT:
                jobs.append(os.path.join(dirpath, n))

    if not jobs:
        sys.exit("No audio in music/. Drop files into music/<Station Name>/ first.")

    before = after = 0
    for src in jobs:
        rel = os.path.relpath(src, MUSIC)
        size0 = os.path.getsize(src)
        stem = os.path.splitext(src)[0]
        tmp = stem + ".__opt.mp3"

        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
               "-vn",                          # drop any embedded cover art
               "-map_metadata", "-1",          # and the tag blob with it
               "-c:a", "libmp3lame", "-b:a", bitrate + "k",
               "-ar", "44100"]
        if mono:
            cmd += ["-ac", "1"]
        cmd.append(tmp)

        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(tmp):
            print("  FAILED  %s  %s" % (rel, r.stderr.strip()[:80]))
            continue

        size1 = os.path.getsize(tmp)
        if size1 >= size0:
            os.remove(tmp)
            print("  kept    %-44s already small (%.1f MB)" % (rel[:44], size0 / 1048576))
            before += size0
            after += size0
            continue

        # stash the original rather than destroying it
        dst = os.path.join(BACKUP, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        os.replace(tmp, os.path.splitext(src)[0] + ".mp3")

        before += size0
        after += size1
        print("  %-44s %6.2f -> %5.2f MB  (%d%% off)"
              % (rel[:44], size0 / 1048576, size1 / 1048576,
                 round(100 * (1 - size1 / size0))))

    if before:
        print("\nTOTAL  %.2f MB -> %.2f MB  (%d%% off)   originals in music_original/"
              % (before / 1048576, after / 1048576, round(100 * (1 - after / before))))
    print("Now refresh the manifest:  python pipeline/build_music.py")


if __name__ == "__main__":
    main()
