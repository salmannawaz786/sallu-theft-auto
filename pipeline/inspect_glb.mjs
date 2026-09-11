/* Dump a GLB's node tree, meshes, materials and textures.
   Usage: node pipeline/inspect_glb.mjs <file.glb> [...]  */
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import fs from 'fs';

const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);

function triCount(mesh){
  let n=0;
  for(const p of mesh.listPrimitives()){
    const i=p.getIndices();
    n += i ? i.getCount()/3 : p.getAttribute('POSITION').getCount()/3;
  }
  return Math.round(n);
}

for (const f of process.argv.slice(2)) {
  const doc = await io.read(f);
  const root = doc.getRoot();
  console.log('\n=== ' + f + '  (' + (fs.statSync(f).size/1048576).toFixed(2) + ' MB) ===');
  let total=0;
  for (const m of root.listMeshes()) total += triCount(m);
  console.log('meshes=' + root.listMeshes().length + '  tris=' + total +
              '  materials=' + root.listMaterials().length +
              '  textures=' + root.listTextures().length);

  const walk = (node, d) => {
    const mesh = node.getMesh();
    const t = node.getTranslation().map(v=>+v.toFixed(2));
    console.log('  '.repeat(d+1) + '- ' + (node.getName()||'(unnamed)') +
      (mesh ? '  [mesh ' + triCount(mesh) + ' tris, prims ' + mesh.listPrimitives().length + ']' : '') +
      '  t=' + JSON.stringify(t));
    node.listChildren().forEach(c => walk(c, d+1));
  };
  for (const sc of root.listScenes()) sc.listChildren().forEach(n => walk(n, 0));

  console.log('  materials: ' + root.listMaterials().map(m =>
    (m.getName()||'?') + '{' +
    (m.getBaseColorTexture()?'base ':'') +
    (m.getNormalTexture()?'norm ':'') +
    (m.getMetallicRoughnessTexture()?'mr ':'') +
    'rough=' + m.getRoughnessFactor().toFixed(2) +
    ',metal=' + m.getMetallicFactor().toFixed(2) + '}'
  ).join('  '));
  console.log('  textures: ' + root.listTextures().map(t => {
    const im=t.getImage();
    return (t.getName()||'?') + '(' + (t.getMimeType()||'?').split('/')[1] + ',' +
           (im?Math.round(im.byteLength/1024):0) + 'KB)';
  }).join(' '));
}
