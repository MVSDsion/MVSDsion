"""Roblox ``.mesh`` files (versions 1-4) to OBJ text with UVs and normals."""

from __future__ import annotations

import re
import struct

from .studio import StudioError

_NUMBER = re.compile(rb'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def is_mesh(data: bytes) -> bool:
    return data.startswith(b'version ')


def mesh_to_obj(data: bytes) -> str:
    try:
        return _convert(data)
    except (struct.error, ValueError, IndexError) as exc:
        raise StudioError(f'The Roblox mesh could not be read ({exc})') from exc


def _convert(data: bytes) -> str:
    newline = data.index(b'\n')
    version = data[8:newline].decode('ascii', 'ignore').strip()
    major = int(version.split('.')[0])
    body = data[newline + 1 :]
    verts: list[tuple[float, ...]] = []
    faces: list[tuple[int, int, int]] = []
    if major == 1:
        values = [float(x) for x in _NUMBER.findall(b' '.join(body.split(b'\n')[1:]))]
        scale = 0.5 if version.startswith('1.00') else 1.0
        count = len(values) // 9
        for i in range(count):
            px, py, pz, nx, ny, nz, u, v, _w = values[i * 9 : (i + 1) * 9]
            verts.append((px * scale, py * scale, pz * scale, nx, ny, nz, u, v))
        faces = [(i, i + 1, i + 2) for i in range(0, count - count % 3, 3)]
    else:
        lods = bones = 0
        if major == 2:
            header, vsize, fsize, nv, nf = struct.unpack_from('<HBBII', body, 0)
        elif major == 3:
            header, vsize, fsize, _ls, lods, nv, nf = struct.unpack_from('<HBBHHII', body, 0)
        elif major == 4:
            header, _lt, nv, nf, lods, bones = struct.unpack_from('<HHIIHH', body, 0)
            vsize, fsize = 40, 12
        else:
            raise ValueError(f'mesh version {version} is not supported')
        if fsize != 12:
            raise ValueError('unexpected face size')
        offset = header
        for i in range(nv):
            verts.append(struct.unpack_from('<8f', body, offset + i * vsize))
        offset += nv * vsize
        if major == 4 and bones > 0:
            offset += nv * 8  # Skinning data
        indices = struct.unpack_from(f'<{nf * 3}I', body, offset)
        offset += nf * 12
        if major >= 3 and lods >= 2:  # Highest detail only
            first, second = struct.unpack_from('<2I', body, offset)
            indices = indices[first * 3 : second * 3]
        faces = [(indices[i], indices[i + 1], indices[i + 2]) for i in range(0, len(indices) - 2, 3)]
    if not verts or not faces or max(max(face) for face in faces) >= len(verts):
        raise ValueError('the mesh is empty or damaged')
    lines = [f'# Converted from Roblox mesh v{version}']
    lines += ['v {:.6f} {:.6f} {:.6f}'.format(*v[:3]) for v in verts]
    lines += [f'vt {v[6]:.6f} {1 - v[7]:.6f}' for v in verts]
    lines += ['vn {:.6f} {:.6f} {:.6f}'.format(*v[3:6]) for v in verts]
    lines += [f'f {a + 1}/{a + 1}/{a + 1} {b + 1}/{b + 1}/{b + 1} {c + 1}/{c + 1}/{c + 1}' for a, b, c in faces]
    return '\n'.join(lines) + '\n'
