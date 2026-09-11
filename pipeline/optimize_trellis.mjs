/**
 * Optimize the 5 Trellis AI-generated car GLBs for the web.
 *
 * Same recipe as pipeline/optimize_models.sh, ported to Node so it runs on
 * Windows without bash:
 *   prune -> dedup -> weld -> simplify (~12k tris) -> quantize -> textures <=512px
 *
 * Usage:  node pipeline/optimize_trellis.mjs
 * Input:  cars/trellis2-*.glb   (5 files, ~5MB each)
 * Output: meshes/car_trellis_1.glb .. car_trellis_5.glb
 */

import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import {
  prune,
  dedup,
  flatten,
  weld,
  simplify,
  quantize,
  textureCompress,
} from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';
import { promises as fs } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const SRC_DIR = path.join(ROOT, 'cars');
const OUT_DIR = path.join(ROOT, 'meshes');

const TARGET_TRIS = 12000;
const TEX_CAP = 512;

/* Stable mapping: source file -> output name. Order matches the 5 trellis2
   files found in cars/ (sorted alphabetically for determinism). */
const SOURCES = [
  'trellis2-522513e4.glb',
  'trellis2-bda8c883.glb',
  'trellis2-ccba4fef.glb',
  'trellis2-dbe5cc04.glb',
  'trellis2-e72a863e.glb',
];

const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);

function triCount(doc) {
  let n = 0;
  for (const mesh of doc.getRoot().listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const idx = prim.getIndices();
      n += idx ? idx.getCount() / 3 : prim.getAttribute('POSITION').getCount() / 3;
    }
  }
  return Math.round(n);
}

function bbox(doc) {
  let min = [Infinity, Infinity, Infinity];
  let max = [-Infinity, -Infinity, -Infinity];
  for (const mesh of doc.getRoot().listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const pos = prim.getAttribute('POSITION');
      if (!pos) continue;
      const arr = pos.getArray();
      for (let i = 0; i < arr.length; i += 3) {
        for (let k = 0; k < 3; k++) {
          if (arr[i + k] < min[k]) min[k] = arr[i + k];
          if (arr[i + k] > max[k]) max[k] = arr[i + k];
        }
      }
    }
  }
  return {
    size: [max[0] - min[0], max[1] - min[1], max[2] - min[2]],
    min, max,
  };
}

async function optimize(srcPath, outPath) {
  const srcSize = (await fs.stat(srcPath)).size;
  const doc = await io.read(srcPath);
  const trisBefore = triCount(doc);

  /* prune/dedup first so we never spend effort simplifying geometry that is
     about to be thrown away. flatten() merges all primitives into one mesh
     so the simplifier sees the whole car as a single problem, not 5 separate
     ones that each hit their own floor. weld() merges split vertices that
     would otherwise block edge collapse. */
  await doc.transform(prune(), dedup(), flatten(), weld());

  const trisWelded = triCount(doc);
  if (trisWelded > TARGET_TRIS) {
    const ratio = TARGET_TRIS / trisWelded;
    await MeshoptSimplifier.ready;
    /* error: 1.0 = no limit, let the ratio drive the decimation. The
       simplifier stops at the target triangle count regardless of error. */
    await doc.transform(
      simplify({ simplifier: MeshoptSimplifier, ratio, error: 1.0 })
    );
  }

  /* Geometry compression only. KHR_mesh_quantization is read natively by
     three.js r160 - no decoder script needed at runtime. */
  await doc.transform(quantize());

  /* Textures: cap at 512px, re-encode. sharp is the backend here; if it
     fails on this machine (known issue per optimize_models.sh comments),
     we catch and keep the original texture data. */
  try {
    await doc.transform(
      textureCompress({
        encoder: (await import('sharp')).default,
        targetFormat: 'jpeg',
        quality: 85,
        resize: [TEX_CAP, TEX_CAP],
      })
    );
  } catch (e) {
    console.warn(`  ! texture compress failed (${e.message}), keeping originals`);
  }

  await io.write(outPath, doc);
  const outSize = (await fs.stat(outPath)).size;
  const trisAfter = triCount(doc);
  const bb = bbox(doc);

  return { srcSize, outSize, trisBefore, trisAfter, bb };
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });

  console.log('Trellis car optimizer');
  console.log(`  target: ${TARGET_TRIS} tris, textures <= ${TEX_CAP}px\n`);

  const results = [];
  for (let i = 0; i < SOURCES.length; i++) {
    const src = path.join(SRC_DIR, SOURCES[i]);
    const out = path.join(OUT_DIR, `car_trellis_${i + 1}.glb`);
    try {
      await fs.access(src);
    } catch {
      console.warn(`  missing ${SOURCES[i]}, skipping`);
      continue;
    }
    process.stdout.write(`  ${SOURCES[i]} -> car_trellis_${i + 1}.glb ... `);
    const r = await optimize(src, out);
    results.push({ name: `car_trellis_${i + 1}`, ...r });
    console.log(
      `${(r.srcSize / 1e6).toFixed(1)}MB -> ${(r.outSize / 1e3).toFixed(0)}KB  ` +
      `(${r.trisBefore} -> ${r.trisAfter} tris)`
    );
  }

  console.log('\nBounding boxes (for CAR_DIMS):');
  for (const r of results) {
    const [w, h, l] = r.bb.size;
    console.log(
      `  ${r.name}: l=${l.toFixed(2)} w=${w.toFixed(2)} h=${h.toFixed(2)}  ` +
      `(raw model units, pre-normalization)`
    );
  }

  const totalIn = results.reduce((s, r) => s + r.srcSize, 0);
  const totalOut = results.reduce((s, r) => s + r.outSize, 0);
  console.log(
    `\nTotal: ${(totalIn / 1e6).toFixed(1)}MB -> ${(totalOut / 1e6).toFixed(2)}MB ` +
    `(${((1 - totalOut / totalIn) * 100).toFixed(0)}% smaller)`
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
