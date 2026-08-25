# Sallu Theft Auto: Web Edition

An open-world driving game that runs in a browser tab. No engine, no install,
no build step — one HTML file and a folder of assets.

**[▶ Play it](https://sallu-theft-auto.pages.dev/)**

![Sallu Theft Auto](docs/screenshot.jpg)

---

## The idea worth stealing

Most driving games track a wanted level. This one tracks **who saw you**.

Pedestrians hold a short memory of what they witnessed. Commit a crime with
nobody around and nothing happens — literally nothing, there is no global
observer. Do it in a crowd and a witness breaks off, runs, and reports a
description of your vehicle to the police.

That description degrades. A witness far away, or one repeating something they
were told rather than saw, gets details wrong — usually the colour. The police
then hunt for *the car they were told about*, not the car you are in. Change
vehicles and the manhunt is chasing a description that no longer matches you.

You can walk up to any pedestrian and press `E` to ask what they saw.

---

## Built with

| | |
|---|---|
| **Rendering** | three.js (WebGL2), custom post chain — bloom, SMAA, colour grade |
| **Physics** | hand-written; no physics library |
| **Characters** | skinned skeletal animation, gait driven procedurally |
| **Audio** | Web Audio — synthesized engine, tyre squeal, and a full music generator |
| **Assets** | textures generated with FLUX.2, meshes with Hunyuan3D, on Beam.cloud |
| **Ship size** | ~8 MB total |

Everything is plain ES modules loaded from a CDN. Clone it, open it, it runs.

---

## Things that were harder than they look

**Vehicle handling.** The naive approach rebuilds the velocity vector in the
car's new heading each frame, which quietly means infinite grip — the car
turns like a mouse cursor. Here the body rotates and the momentum does not;
the angle between them is the slip angle, and grip is what eats it. That one
change is the difference between steering a cursor and driving a car. Steering
authority also falls away with speed, so a car is twitchy in a car park and
stable at 130 km/h.

**Everything is level-of-detail.** A pedestrian costs five draw calls to keep
their arms and legs swinging, which is five calls wasted once a stride is no
longer legible. Past that distance they collapse to a single baked mesh, and
past 130 m they are dropped entirely. The result: **26 pedestrians cost 10
draw calls**, where 12 pedestrians previously cost 72. Vehicles, parked cars
and shadows all get the same treatment.

**Collision uses a real footprint.** A bounding circle per car meant two
saloons "collided" with three metres of daylight between them. Reporting how
far each body reaches along the line joining the two centres fixed the obvious
case and left a subtler one: that measurement is a *support radius* - the width
of the car's shadow on that line, not the distance to its panels - so it is
only tight when two boxes meet face to face. Approached diagonally it still
claimed contact through a metre of clear air, and the same axis-aligned bound
wrapped around a rotated car padded every kerb, bin and parked car by up to
2.4m at forty-five degrees. Contact is now separating-axis: four axes for two
boxes, exact, with the shallowest overlap as the push-out direction. Measured
worst-case phantom contact went from 1.19m to 0.24m on foot, and from 2.36m to
zero for a car passing a litter bin.

**Which way round is a car modelled?** Two automated attempts at this failed,
because both asked each body to decide on its own evidence, and per body the
evidence genuinely conflicts - a pickup's cab really is forward of centre and a
coupe's really is back. The hand list that replaced them had the same weakness
in slower form: it recorded one body as reversed, and reversing that one body
is what put it out of step with the other nine, which is what "the Ferrari
drives backwards" was. The question with a reliable answer is about the *pack*,
not the body: ten cars from one artist share an axis, so each body votes with
the evidence it has and the majority turns all ten together. A pickup bed and a
symmetric coupe can both vote wrong without changing the result.

**The frame-rate meter was lying.** The physics timestep is clamped so a stall
cannot tunnel a car through a wall. Feeding that clamped number to the FPS
counter put a hard floor of exactly 20 fps on the display — any real rate below
20 still read as 20, and no graphics setting appeared to change anything. There
is now a flight recorder on `F4` that dumps a per-second history splitting each
frame into simulation time versus render time.

**Audio that does not leak.** Every one-shot sound used to leave its gain node
wired to the destination forever. Web Audio keeps processing every connected
node whether or not it is making sound, so a few minutes of traffic built up
hundreds of live nodes and the frame rate went with it. Every voice now tears
itself down when it ends.

---

## The radio

Five stations, generated live in the browser rather than streamed — no files,
nothing to license, no download. Each has its own tempo, key, chord progression
and filter character, scheduled against the audio clock so the music stays
sample-accurate even when the renderer stutters.

Drop your own tracks into `music/<Station Name>/` and they appear on the dial
alongside them.

---

## Controls

| | |
|---|---|
| `W A S D` | drive / walk |
| `Mouse` | look |
| `Click` / `Q` | throw a punch (on foot) |
| `F` | enter / exit vehicle |
| `Shift` | sprint |
| `Space` | handbrake |
| `E` | ask a witness what they saw |
| `M` | map |
| `[` `]` `N` | radio: station, station, skip |
| `T` / `Shift+T` | time of day / lock night |
| `R` | rain |
| `G` | graphics tier |
| `F3` / `F4` | stats / profile dump |

---

## Running it

Needs a local server — `file://` blocks the textures.

```bash
python -m http.server 8123
```

Then open `http://localhost:8123/`.

---

## Credits and licensing

The code is mine. The third-party models are **CC BY 4.0** and their
attribution is a licence condition, not a courtesy — see [`CREDITS.txt`](CREDITS.txt)
and keep it with any copy you distribute.

Two models in the working tree are **not** redistributable and are excluded
from the deployed build: `old_car.glb` (Sketchfab Standard) and
`grungy_little_car.glb` (CC BY-NC). Do not add them to a public or commercial
build.



---

Built by **[Salman Nawaz](https://salmannawaz.com)** · SalluLabs
