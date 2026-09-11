/**
 * Diagnostic: dump structure of the optimized Trellis GLBs so we can see
 * exactly what the game's loader has to work with.
 */
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);

for (const n of [1, 2, 3, 4, 5]) {
  const p = path.join(ROOT, 'meshes', `car_trellis_${n}.glb`);
  const doc = await io.read(p);
  const root = doc.getRoot();
  console.log(`\n=== car_trellis_${n}.glb ===`);
  console.log('meshes:', root.listMeshes().length,
    '| materials:', root.listMaterials().length,
    '| textures:', root.listTextures().length);

  for (const mesh of root.listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const attrs = prim.listAttributes().map(a => a.getName()).join(',');
      const idx = prim.getIndices();
      const tris = idx ? idx.getCount() / 3 : prim.getAttribute('POSITION').getCount() / 3;
      const mat = prim.getMaterial();
      const matInfo = mat ? `${mat.getName()} doubleSided=${mat.getDoubleSided()}` : 'null';
      console.log(`  prim: tris=${Math.round(tris)} attrs=[${attrs}] mat=${matInfo}`);
      // vertex color check
      const vc = prim.getAttribute('COLOR_0');
      if (vc) {
        const arr = vc.getArray();
        let allZero = true;
        for (let i = 0; i < arr.length; i++) if (arr[i] > 0.01) { allZero = false; break; }
        console.log(`    COLOR_0 present, ${allZero ? 'ALL ~ZERO (invisible!)' : 'has values'}`);
      }
      // bbox
      const pos = prim.getAttribute('POSITION');
      const arr = pos.getArray();
      let mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
      for (let i = 0; i < arr.length; i += 3) {
        for (let k = 0; k < 3; k++) {
          if (arr[i + k] < mn[k]) mn[k] = arr[i + k];
          if (arr[i + k] > mx[k]) mx[k] = arr[i + k];
        }
      }
      console.log(`    bbox min=[${mn.map(v => v.toFixed(2)).join(', ')}] max=[${mx.map(v => v.toFixed(2)).join(', ')}]`);
    }
  }
  for (const mat of root.listMaterials()) {
    console.log(`  material "${mat.getName()}": baseColor=${JSON.stringify(mat.getBaseColorFactor())} metallic=${mat.getMetallicFactor()} rough=${mat.getRoughnessFactor()}`);
  }
}
