/**
 * Web-sized copies of the models the Godot build already uses.
 *
 * The Godot assets are tuned for a desktop GPU: 95k-triangle cars with 2048px
 * textures (5 MB each), 94k-triangle characters. A phone cannot afford ten of
 * those, so this makes lighter copies:
 *
 *   cars        ~22k triangles, 1024px webp   (the same budget meshes/car_taxi.glb has)
 *   characters  ~22k triangles, 1024px webp
 *   multi-part  (F-150, police car) are already 17-18k - only the KHR transmission
 *               extension is removed, because it forces a second full-screen
 *               render pass for the whole scene as soon as one is on screen.
 *
 * Usage:  node pipeline/optimize_web_assets.mjs
 */
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { prune, dedup, weld, simplify, textureCompress } from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';
import sharp from 'sharp';
import { promises as fs } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(ROOT, 'godot/assets');
const OUT = path.join(ROOT, 'meshes');

const JOBS = [
  // single-mesh TRELLIS cars: simplify + 1024 textures.
  // (car_t1..t5 are deliberately absent: they are the same five scans as the
  // car_hatchback/muscle/sport/suv/taxi the web already ships.)
  { in: 'car_new_a.glb', out: 'car_new_a.glb', tris: 22000, tex: 1024 },
  { in: 'car_new_b.glb', out: 'car_new_b.glb', tris: 22000, tex: 1024 },
  // multi-part cars: keep the geometry, drop transmission
  { in: 'car_f150.glb',        out: 'car_f150.glb',        noTransmission: true },
  { in: 'car_police_new.glb',  out: 'car_police_new.glb',  noTransmission: true },
  // characters
  { in: 'char_player.glb', out: 'char_player.glb', tris: 22000, tex: 1024 },
  { in: 'char_hijab.glb',  out: 'char_hijab.glb',  tris: 22000, tex: 1024 },
  { in: 'char_duke.glb',   out: 'char_duke.glb',   tex: 1024 },
];

const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
await MeshoptSimplifier.ready;

function count(doc) {
  let t = 0;
  for (const m of doc.getRoot().listMeshes())
    for (const p of m.listPrimitives()) {
      const i = p.getIndices();
      t += i ? i.getCount() / 3 : p.getAttribute('POSITION').getCount() / 3;
    }
  return Math.round(t);
}

for (const job of JOBS) {
  const doc = await io.read(path.join(SRC, job.in));
  const before = count(doc);
  const beforeBytes = (await fs.stat(path.join(SRC, job.in))).size;

  if (job.noTransmission) {
    const T = ALL_EXTENSIONS.find((e) => e.EXTENSION_NAME === 'KHR_materials_transmission');
    for (const mat of doc.getRoot().listMaterials()) {
      const t = mat.getExtension('KHR_materials_transmission');
      if (!t) continue;
      mat.setExtension('KHR_materials_transmission', null);
      // transmission was doing the see-through; plain alpha does it for free
      mat.setAlphaMode('BLEND');
      const c = mat.getBaseColorFactor();
      mat.setBaseColorFactor([c[0], c[1], c[2], Math.min(c[3], 0.3)]);
    }
    for (const e of doc.getRoot().listExtensionsUsed())
      if (e.extensionName === 'KHR_materials_transmission' && !doc.getRoot().listMaterials().some((m) => m.getExtension(e.extensionName))) e.dispose();
  }

  const steps = [prune(), dedup()];
  if (job.tris && before > job.tris) {
    steps.push(
      weld({ tolerance: 0.0001 }),
      simplify({ simplifier: MeshoptSimplifier, ratio: job.tris / before, error: 0.5 }),
    );
  }
  if (job.tex) steps.push(textureCompress({ encoder: sharp, targetFormat: 'webp', resize: [job.tex, job.tex] }));
  steps.push(prune());
  await doc.transform(...steps);

  await io.write(path.join(OUT, job.out), doc);
  const afterBytes = (await fs.stat(path.join(OUT, job.out))).size;
  console.log(`${job.out.padEnd(20)} tris ${String(before).padStart(6)} -> ${String(count(doc)).padStart(6)}   ${(beforeBytes / 1048576).toFixed(1)} MB -> ${(afterBytes / 1048576).toFixed(2)} MB`);
}
