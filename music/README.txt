RADIO STATIONS
==============

Each SUBFOLDER in here is a station. Drop audio files inside it.

    music/
      Vice FM/        <- station name is the folder name
        track01.mp3
        track02.mp3
      Night Drive/
        whatever.ogg

Files sitting loose in music/ (not in a subfolder) become a station
called "Local".

Supported: .mp3 .ogg .m4a .wav .flac .opus .aac .webm

The game finds stations two ways, in this order:

  1. music/manifest.json, if it exists. Build or refresh it with:
         python pipeline/build_music.py
     Use this if you serve the game from anything other than
     `python -m http.server` - most static hosts do not expose
     directory listings.

  2. Failing that, it reads the directory listing the dev server
     returns. `python -m http.server` provides one, so during
     development you can just add files and reload - no manifest
     needed.

In game (while in a vehicle):
    [  and  ]   previous / next station
    N           skip track
    0           radio off
