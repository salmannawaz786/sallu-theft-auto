#!/usr/bin/env bash
# Shrink the third-party GLBs for the web without a decoder dependency.
#
# Two different problems live in these files:
#   * some are texture-bound (grungy_little_car is 97% PNG, 2.6k triangles)
#   * some are geometry-bound (police_car is 256k triangles for one vehicle)
# so each file gets a triangle budget and every file gets its textures capped.
#
# Everything here stays inside what three.js r160 reads natively:
#   KHR_mesh_quantization  - vertex data at 16/8 bit, no decoder
#   EXT_texture_webp       - no decoder
# Draco and meshopt would go smaller still but need a decoder script at runtime,
# which is a hard failure mode if the CDN is slow. Not worth it here.
set -u
GT="./node_modules/.bin/gltf-transform"
SRC="car models thirdparty"
OUT="models"
mkdir -p "$OUT"

# name                                   target-tris  texture-cap
JOBS="
car.glb:15000:1024
cyberpunk_character.glb:24500:512
halena_female_3_d_character.glb:18000:512
generic_passenger_car_pack.glb:69312:512
car_for_games_unity.glb:16000:1024
grungy_little_car.glb:2600:1024
low-poly_city_buildings.glb:7150:1024
low_poly_night_city_building_skyline.glb:6076:1024
old_car.glb:15000:1024
police_car.glb:16000:1024
"

for job in $JOBS; do
  f="${job%%:*}"; rest="${job#*:}"; tris="${rest%%:*}"; cap="${rest##*:}"
  [ -f "$SRC/$f" ] || { echo "missing $f"; continue; }
  src="$SRC/$f"; tmp="$OUT/.tmp_$f"; dst="$OUT/$f"

  cur=$(node -e "
    const fs=require('fs');const b=fs.readFileSync(process.argv[1]);let o=12,j=null;
    while(o<b.length){const l=b.readUInt32LE(o),t=b.readUInt32LE(o+4);
      if(t===0x4E4F534A)j=JSON.parse(b.slice(o+8,o+8+l).toString('utf8'));o+=8+l;}
    let n=0;for(const m of j.meshes||[])for(const p of m.primitives||[]){
      const a=j.accessors[p.indices];n+=a?a.count/3:0;}
    console.log(Math.round(n));" "$src")

  ratio=$(node -e "console.log(Math.min(1,(+process.argv[1])/Math.max(1,+process.argv[2])).toFixed(4))" "$tris" "$cur")

  echo "--- $f : $cur tris -> target $tris (ratio $ratio), textures <= ${cap}px"

  # prune/dedup first so we never spend effort simplifying geometry that is
  # about to be thrown away, then weld (simplify needs shared vertices to
  # collapse across) and only then decimate.
  "$GT" prune  "$src" "$tmp" >/dev/null 2>&1 || cp "$src" "$tmp"
  "$GT" dedup  "$tmp" "$tmp" >/dev/null 2>&1
  "$GT" weld   "$tmp" "$tmp" >/dev/null 2>&1
  if [ "$(node -e "console.log(+process.argv[1]<0.99?1:0)" "$ratio")" = "1" ]; then
    "$GT" simplify "$tmp" "$tmp" --ratio "$ratio" --error 0.008 >/dev/null 2>&1
  fi
  # Geometry compression only. gltf-transform's texture pass uses sharp, whose
  # libvips build on this machine fails on ordinary RGB PNGs
  # ("colourspace: parameter space not set"), so textures go through PIL below.
  "$GT" quantize "$tmp" "$tmp" >/dev/null 2>&1
  python pipeline/shrink_textures.py "$tmp" "$dst" --cap "$cap" --quality 88 || cp "$tmp" "$dst"
  rm -f "$tmp"
done
rm -f "$OUT"/.tmp_*
