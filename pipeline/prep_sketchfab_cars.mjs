/**
 * Prepare the two Sketchfab cars for the game.
 *
 * These arrive as Sketchfab FBX conversions: deep node trees, per-material
 * mesh splits, and - on the e-tron - a fully modelled interior that is 36% of
 * its triangles and can never be seen from outside a GTA-style camera.
 *
 * Node NAMES are load-bearing here: the game's loader finds wheels by matching
 * /wheel|tyre|rotor|brake/ against them, so `flatten` and `join` are
 * deliberately not used - they would merge the wheels into the body and the
 * car would arrive as one rigid lump again.
 *
 * Usage: node pipeline/prep_sketchfab_cars.mjs
 */
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { prune, dedup, weld, simplify, textureCompress } from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';
import sharp from 'sharp';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);

const JOBS = [
  { src: '2005_car_audi.glb',              out: 'meshes/car_audi_a4.glb',  tris: 9000,  tex: 1024, dropInterior: false },
  { src: '2018_audi_e-tron_gt_concept.glb', out: 'meshes/car_etron_gt.glb', tris: 16000, tex: 1024, dropInterior: true  },
];

const triCount = doc => {
  let n = 0;
  for (const m of doc.getRoot().listMeshes())
    for (const p of m.listPrimitives()) {
      const i = p.getIndices();
      n += i ? i.getCount() / 3 : p.getAttribute('POSITION').getCount() / 3;
    }
  return Math.round(n);
};

for (const job of JOBS) {
  const srcPath = path.join(ROOT, job.src);
  if (!fs.existsSync(srcPath)) { console.log('SKIP (missing): ' + job.src); continue; }
  const doc = await io.read(srcPath);
  const before = triCount(doc);

  if (job.dropInterior) {
    /* Detach every INT: node. Dropping the mesh alone would leave the node,
       and prune() only collects what nothing references any more. */
    let dropped = 0;
    for (const node of doc.getRoot().listNodes()) {
      if (/(^|:)INT:/.test(node.getName() || '')) { node.dispose(); dropped++; }
    }
    console.log('  dropped ' + dropped + ' interior nodes');
  }

  await doc.transform(
    dedup(),
    weld(),
    simplify({ simplifier: MeshoptSimplifier, ratio: 0.01, error: 0.001 }),
    prune(),
    textureCompress({ encoder: sharp, targetFormat: 'webp', resize: [job.tex, job.tex] }),
  );

  const after = triCount(doc);
  await io.write(path.join(ROOT, job.out), doc);
  const kb = Math.round(fs.statSync(path.join(ROOT, job.out)).size / 1024);
  console.log(job.src + '  ->  ' + job.out);
  console.log('  tris ' + before + ' -> ' + after + '   ' + kb + ' KB');
}
