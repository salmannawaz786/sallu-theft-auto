"""
Write music/manifest.json from whatever is sitting in music/.

The game can read a dev server's directory listing directly, but most static
hosts do not serve one - so anything you intend to deploy needs this manifest.

    python pipeline/build_music.py
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MUSIC = os.path.join(HERE, "..", "music")
EXT = {".mp3", ".ogg", ".m4a", ".wav", ".flac", ".opus", ".aac", ".webm"}


def tracks_in(folder):
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [n for n in names
            if os.path.splitext(n)[1].lower() in EXT
            and os.path.isfile(os.path.join(folder, n))]


def main():
    if not os.path.isdir(MUSIC):
        raise SystemExit("no music/ folder next to index.html")

    stations = []

    loose = tracks_in(MUSIC)
    if loose:
        stations.append({"name": "Local", "tracks": loose})

    for entry in sorted(os.listdir(MUSIC)):
        sub = os.path.join(MUSIC, entry)
        if not os.path.isdir(sub):
            continue
        t = tracks_in(sub)
        if t:
            stations.append({"name": entry, "tracks": [entry + "/" + n for n in t]})

    out = os.path.join(MUSIC, "manifest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"stations": stations}, f, indent=1, ensure_ascii=False)

    total = sum(len(s["tracks"]) for s in stations)
    if not stations:
        print("No audio found. Drop files into music/<Station Name>/ and re-run.")
    for s in stations:
        print("  %-24s %d track%s" % (s["name"], len(s["tracks"]),
                                      "" if len(s["tracks"]) == 1 else "s"))
    print("%d station(s), %d track(s) -> %s" % (len(stations), total, out))


if __name__ == "__main__":
    main()
