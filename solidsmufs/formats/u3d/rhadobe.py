"""Adobe's private U3D mesh ("RHAdobeMeshResource", Right Hemisphere's compression, Acrobat 8.1 and later), decoded by a
third-party JavaScript decoder run in PySide6's JavaScript engine. See vendor/README.md: that file has no license and is
used internally only. Without it, these meshes are reported as unreadable, as before.
"""

import os
from pathlib import Path

import numpy as np

from .stream import U3dError

NAME = "RHAdobeMeshResource"
GUID = (0x96A804A6, 0x3FB9, 0x43C5, bytes((0xB2, 0xDF, 0x2A, 0x31, 0xB5, 0x56, 0x93, 0x40)))
DECODER = Path(__file__).with_name("vendor") / "u3d-rhadobe-mesh.js"
_CLI = "if (typeof require !== 'undefined' && require.main === module)"  # its Node.js command line, which isn't needed here

# the engine has no TextDecoder: names are UTF-8
_TEXT_DECODER = """
var TextDecoder = function () {};
TextDecoder.prototype.decode = function (u8) {
  var out = '', i = 0;
  while (i < u8.length) {
    var c = u8[i++], code;
    if (c < 0x80) code = c;
    else if (c < 0xE0) code = ((c & 31) << 6) | (u8[i++] & 63);
    else if (c < 0xF0) { code = ((c & 15) << 12) | ((u8[i++] & 63) << 6); code |= u8[i++] & 63; }
    else { code = ((c & 7) << 18) | ((u8[i++] & 63) << 12); code |= (u8[i++] & 63) << 6; code |= u8[i++] & 63; }
    out += String.fromCodePoint(code);
  }
  return out;
};
"""

# what comes back: plain buffers, which arrive as bytes
_CALL = """(function (buf) {
  var u8 = new Uint8Array(buf);
  var m = RHAdobeMesh.decodeBlock(u8, 0, u8.length);
  var materials = m.materials.map(function (x) { return [x.hasDiffuse, x.hasSpecular, x.layers]; });
  return { name: m.name, positions: m.positions.slice().buffer, indices: new Uint32Array(m.indices).buffer,
           materialIds: new Uint32Array(m.matIds).buffer, materials: JSON.stringify(materials), badIndex: m.badIndex,
           exactEnd: m.exactEnd };
})"""

_engine = None
_decode = None


def available():
    return DECODER.is_file()


def _function():
    global _engine, _decode
    if _decode is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtQml import QJSEngine
        if QCoreApplication.instance() is None:
            _function.app = QCoreApplication([])
        _engine = QJSEngine()
        source = DECODER.read_text(encoding="utf-8")
        cut = source.find(_CLI)
        loaded = _engine.evaluate(_TEXT_DECODER + (source[:cut] if cut >= 0 else source), DECODER.name)
        if loaded.isError():
            raise U3dError(f"Adobe's mesh decoder couldn't be loaded ({loaded.toString()}).")
        _decode = _engine.evaluate(_CALL)
    return _engine, _decode


def decode(body):
    """(name, points (n, 3), triangles (m, 3), material of each triangle, materials as (diffuse, specular, layers))."""
    import json
    from PySide6.QtCore import QByteArray
    engine, call = _function()
    out = call.call([engine.toScriptValue(QByteArray(body))])
    if out.isError():
        raise U3dError(f"Adobe's mesh format couldn't be read: {out.toString().removeprefix('Error: ')}.")

    def buffer(key, kind, width):
        raw = out.property(key).toVariant()
        return np.frombuffer(bytes(raw) if raw is not None else b"", kind).reshape(-1, width)

    points = buffer("positions", "<f4", 3).astype(float)
    triangles = buffer("indices", "<u4", 3).astype(np.int64)
    materials = [tuple(m) for m in json.loads(out.property("materials").toString())]
    ids = buffer("materialIds", "<u4", 1).ravel().astype(np.int64)
    if out.property("badIndex").toInt() or (len(triangles) and triangles.max() >= len(points)):
        raise U3dError("Adobe's mesh format: a triangle uses a point that isn't there.")
    return out.property("name").toString(), points, triangles, ids, materials
