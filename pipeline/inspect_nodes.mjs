/**
 * Dump node hierarchy + transforms of Trellis GLBs (source and optimized)
 * to see what orientation/scale the game actually receives.
 */
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);

const files = [
  'cars/trellis2-522513e4.glb',
  'meshes/car_trellis_1.glb',
  'meshes/car_trellis_4.glb',
];

for (const f of files) {
  const doc = await io.read(path.join(ROOT, f));
  const root = doc.getRoot();
  console.log(`\n=== ${f} ===`);
  const walk = (n, depth) => {
    const t = n.getWorldTransform ? n.getWorldTransform() : null;
    const trs = t ? `world=[${t.map(v => v.toFixed(3)).join(', ')}]` : '';
    const mesh = n.getMesh ? n.getMesh() : null;
    console.log(`${'  '.repeat(depth)}node "${n.getName()}" ${mesh ? 'MESH' : ''} ${trs}`);
    for (const c of n.listChildren()) walk(c, depth + 1);
  };
  for (const s of root.listScenes()) for (const c of s.listChildren()) walk(c, 0);
  // extension usage
  const exts = doc.getExtensionsUsed().map(e => e.extensionName);
  console.log('extensions used:', exts.join(', ') || '(none)');
}
