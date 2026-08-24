# Watermark

Attribution is embedded in **four** places. They are deliberately spread out so
that deleting one does not silently remove the credit, but none of them are
obfuscated and none of them break the game if taken out. If you have bought a
licence, remove all four.

| # | Where | What to look for |
|---|-------|------------------|
| 1 | HUD element | `<div id="wm">` in the HUD markup, plus its `#wm{...}` CSS rule |
| 2 | Minimap bitmap | end of `drawRadar()` — the `g.fillText('SALLULABS', ...)` block |
| 3 | Browser console | the `console.log` signature block just above `window.__booted=true` |
| 4 | Global object | `window.__STF_BUILD` on the same line |

Removing all four:

1. Delete the `<div id="wm">...</div>` line and the `#wm{...}` CSS rule.
2. In `drawRadar()`, delete the `g.save() ... g.restore()` block that draws
   `SALLULABS` (it sits immediately before the `streetEl.textContent` line).
3. Delete the `try{ console.log(...) }catch(e){}` block.
4. Delete the `window.__STF_BUILD = {...}` line.

Nothing else depends on any of them.

## What this is and is not

This marks authorship. It is not copy protection and does not pretend to be —
anyone determined will find all four in a few minutes with a text search, and
that is fine. The point is that a casual copy keeps the credit attached.

## Third-party assets

The watermark covers **my** code and the generated assets. It does not cover
the third-party models, which carry their own licences and their own
attribution requirements — see `CREDITS.txt`. Those credits are a licence
condition and must stay regardless of anything above.

Two of the models in the wider project are **not** redistributable
(`old_car.glb` is Sketchfab Standard; `grungy_little_car.glb` is CC BY-NC), so
neither is shipped in the deployed build. Do not add them to a public or
commercial build.
