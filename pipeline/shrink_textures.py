"""
Re-encode the textures embedded in a GLB.

gltf-transform's own texture pass is the right tool for this, but its sharp /
libvips build on this machine dies with "colourspace: parameter space not set"
on perfectly ordinary RGB PNGs, so the image work happens in PIL instead and
gltf-transform is left to do geometry only.

Everything here stays in core glTF - JPEG and PNG are both base spec, so no
EXT_texture_webp and no loader extension is needed. That matters more than the
extra 20% WebP would buy: a texture format the loader silently cannot read is
an invisible failure.

    python shrink_textures.py in.glb out.glb [--cap 1024] [--quality 88]
"""

import io
import json
import os
import struct
import sys

from PIL import Image

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def read_glb(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, _ver, _len = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise ValueError(f"{path} is not a GLB")
    off, js, binary = 12, None, b""
    while off < len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        chunk = data[off + 8: off + 8 + clen]
        if ctype == JSON_CHUNK:
            js = json.loads(chunk.decode("utf-8"))
        elif ctype == BIN_CHUNK:
            binary = chunk
        off += 8 + clen
        off += (4 - off % 4) % 4
    return js, binary


def write_glb(path, js, binary):
    jb = json.dumps(js, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    bb = binary + b"\0" * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(jb) + (8 + len(bb) if bb else 0)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(jb), JSON_CHUNK))
        f.write(jb)
        if bb:
            f.write(struct.pack("<II", len(bb), BIN_CHUNK))
            f.write(bb)


def roles(js):
    """Which images are data maps rather than colour, so they can be spared
    aggressive chroma loss. A blocky normal map is far more visible than a
    blocky albedo."""
    data_role = set()
    for mat in js.get("materials", []):
        pbr = mat.get("pbrMetallicRoughness", {})
        for key, holder in (("normalTexture", mat),
                            ("occlusionTexture", mat),
                            ("metallicRoughnessTexture", pbr)):
            t = holder.get(key)
            if t and "index" in t:
                tex = js["textures"][t["index"]]
                src = tex.get("source")
                if src is not None:
                    data_role.add(src)
    return data_role


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    cap = 1024
    quality = 88
    if "--cap" in sys.argv:
        cap = int(sys.argv[sys.argv.index("--cap") + 1])
    if "--quality" in sys.argv:
        quality = int(sys.argv[sys.argv.index("--quality") + 1])

    js, binary = read_glb(src)
    views = js.get("bufferViews", [])
    if not views:
        write_glb(dst, js, binary)
        return

    data_role = roles(js)
    replaced = {}          # bufferView index -> new bytes
    before = after = 0

    for i, img in enumerate(js.get("images", [])):
        bv_i = img.get("bufferView")
        if bv_i is None:
            continue
        bv = views[bv_i]
        start = bv.get("byteOffset", 0)
        raw = binary[start:start + bv["byteLength"]]
        before += len(raw)
        try:
            im = Image.open(io.BytesIO(raw))
            im.load()
        except Exception as e:
            print(f"  image {i}: cannot decode ({e}), left alone")
            after += len(raw)
            continue

        if max(im.size) > cap:
            k = cap / max(im.size)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                           Image.LANCZOS)

        # keep an alpha channel only if it actually varies; a fully opaque
        # alpha channel is a third of the file for nothing
        has_alpha = im.mode in ("RGBA", "LA", "P") and "transparency" in im.info
        if im.mode in ("RGBA", "LA"):
            alpha = im.getchannel("A")
            has_alpha = alpha.getextrema()[0] < 255

        out = io.BytesIO()
        if has_alpha:
            im.convert("RGBA").save(out, "PNG", optimize=True)
            mime = "image/png"
        else:
            q = min(96, quality + 6) if i in data_role else quality
            im.convert("RGB").save(out, "JPEG", quality=q, optimize=True,
                                   subsampling=0 if i in data_role else 2)
            mime = "image/jpeg"
        blob = out.getvalue()

        # never make a texture bigger than it started
        if len(blob) >= len(raw):
            after += len(raw)
            continue

        replaced[bv_i] = blob
        img["mimeType"] = mime
        after += len(blob)

    if not replaced:
        write_glb(dst, js, binary)
        print(f"  no texture savings; copied ({os.path.getsize(src)/1048576:.2f} MB)")
        return

    # Rebuild the binary chunk. Every bufferView is rewritten in index order at
    # 4-byte alignment, which satisfies the accessor alignment rules, and the
    # offsets are remapped as we go.
    out = bytearray()
    for idx, bv in enumerate(views):
        blob = replaced.get(idx)
        if blob is None:
            s = bv.get("byteOffset", 0)
            blob = binary[s:s + bv["byteLength"]]
        pad = (4 - len(out) % 4) % 4
        out.extend(b"\0" * pad)
        bv["byteOffset"] = len(out)
        bv["byteLength"] = len(blob)
        out.extend(blob)

    js["buffers"][0]["byteLength"] = len(out)
    js["buffers"][0].pop("uri", None)
    write_glb(dst, js, bytes(out))
    print(f"  textures {before/1048576:.2f} MB -> {after/1048576:.2f} MB "
          f"({100*(1-after/max(before,1)):.0f}% off)")


if __name__ == "__main__":
    main()
