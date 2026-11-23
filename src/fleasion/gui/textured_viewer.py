"""Fleasion's OBJ viewer with texture support, for the color studio's live preview."""

from __future__ import annotations

import time

import numpy as np
from OpenGL.GL import (  # pyright: ignore[reportMissingTypeStubs]
    GL_CLAMP_TO_EDGE,
    GL_COLOR_BUFFER_BIT,
    GL_COMPILE,
    GL_DEPTH_BUFFER_BIT,
    GL_FLOAT,
    GL_NORMAL_ARRAY,
    GL_TEXTURE_COORD_ARRAY,
    GL_VERTEX_ARRAY,
    GL_LINEAR,
    GL_LINEAR_MIPMAP_LINEAR,
    GL_MODULATE,
    GL_RGBA,
    GL_TEXTURE_2D,
    GL_TEXTURE_ENV,
    GL_TEXTURE_ENV_MODE,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_TRIANGLES,
    GL_UNPACK_ALIGNMENT,
    GL_UNSIGNED_BYTE,
    glBindTexture,
    glCallList,
    glClear,
    glColor3f,
    glDisable,
    glDisableClientState,
    glDrawArrays,
    glEnable,
    glEnableClientState,
    glEndList,
    glGenLists,
    glGenTextures,
    glLoadIdentity,
    glNewList,
    glNormalPointer,
    glPixelStorei,
    glRotatef,
    glTexCoordPointer,
    glTexEnvi,
    glTexImage2D,
    glTexParameteri,
    glTranslatef,
    glVertexPointer,
)
from OpenGL.GL import glGenerateMipmap  # pyright: ignore[reportMissingTypeStubs]
from OpenGL.GL import (  # pyright: ignore[reportMissingTypeStubs]
    GL_DEPTH_TEST,
    GL_FALSE,
    GL_LIGHTING,
    GL_MODELVIEW,
    GL_PROJECTION,
    GL_QUADS,
    GL_TRUE,
    glBegin,
    glDepthMask,
    glEnd,
    glMatrixMode,
    glOrtho,
    glPopMatrix,
    glPushMatrix,
    glTexCoord2f,
    glVertex3f,
)

from ..cache.obj_viewer import ObjViewerWidget

_SPIN_DEGREES_PER_SECOND = 18.0



# Parsed models by OBJ text, shared by the grid cards and the studio window
_PARSED: dict[str, tuple[list, list, list, list, list, list]] = {}  # pyright: ignore[reportMissingTypeArgument]
_PARSED_LIMIT = 12

class TexturedObjViewer(ObjViewerWidget):
    """Draws the model with a texture; ``set_texture`` swaps it instantly (no rebuild).

    The angle uses the website's order (yaw, then pitch, then roll), so the app
    shows exactly the angle the owner picked in the website preview.
    """

    def __init__(self, parent: object = None, *, interactive: bool = True) -> None:
        super().__init__(parent)
        self.uvs: list[list[float]] = []
        self._texture_id = 0
        self._pending: np.ndarray | None = None
        self.show_grid = False
        self.rotation_z = 0.0
        self.interactive = interactive
        self.zoom = -2.05

    def set_auto_rotate(self, enabled: bool) -> None:
        """Slow turn around the vertical axis (Fleasion's own spin is much faster)."""
        self._spin = enabled
        self._last_spin = time.monotonic()

    def _update_tick(self) -> None:
        super()._update_tick()
        if getattr(self, '_spin', False):
            now = time.monotonic()
            self.rotation_y += _SPIN_DEGREES_PER_SECOND * min(now - self._last_spin, 0.1)
            self._last_spin = now
            self.update()

    def set_background(
        self,
        top: tuple[float, float, float],
        bottom: tuple[float, float, float],
        picture: np.ndarray | None = None,
    ) -> None:
        """One color (top == bottom), a gradient, or a picture (RGBA floats) behind the gun."""
        self._bg_colors = (top, bottom)
        if picture is not None:
            self._bg_pending = np.ascontiguousarray(np.clip(picture * 255.0 + 0.5, 0, 255).astype(np.uint8))
        else:
            self._bg_pending = None
            self._bg_texture_size = None
        self.update()

    def _upload_background(self) -> None:
        data = getattr(self, '_bg_pending', None)
        if data is None:
            return
        self._bg_pending = None
        if not getattr(self, '_bg_texture_id', 0):
            self._bg_texture_id = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, self._bg_texture_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        height, width = data.shape[:2]
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        self._bg_texture_size = (width, height)

    def _draw_background(self) -> None:
        """Black by default; the owner can choose colors or a picture on the website."""
        self._upload_background()
        top, bottom = getattr(self, '_bg_colors', ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
        size = getattr(self, '_bg_texture_size', None)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(-1, 1, -1, 1, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glDisable(GL_LIGHTING)
        glDisable(GL_DEPTH_TEST)
        glDepthMask(GL_FALSE)
        if size and getattr(self, '_bg_texture_id', 0):
            # Cover the view without stretching the picture
            view = self.width() / max(self.height(), 1)
            image = size[0] / max(size[1], 1)
            u = min(1.0, view / image) / 2
            v = min(1.0, image / view) / 2
            glEnable(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, self._bg_texture_id)
            glColor3f(1.0, 1.0, 1.0)
            glBegin(GL_QUADS)
            glTexCoord2f(0.5 - u, 0.5 + v)
            glVertex3f(-1.0, -1.0, 0.0)
            glTexCoord2f(0.5 + u, 0.5 + v)
            glVertex3f(1.0, -1.0, 0.0)
            glTexCoord2f(0.5 + u, 0.5 - v)
            glVertex3f(1.0, 1.0, 0.0)
            glTexCoord2f(0.5 - u, 0.5 - v)
            glVertex3f(-1.0, 1.0, 0.0)
            glEnd()
            glDisable(GL_TEXTURE_2D)
        else:
            glBegin(GL_QUADS)
            glColor3f(*top)
            glVertex3f(-1.0, 1.0, 0.0)
            glVertex3f(1.0, 1.0, 0.0)
            glColor3f(*bottom)
            glVertex3f(1.0, -1.0, 0.0)
            glVertex3f(-1.0, -1.0, 0.0)
            glEnd()
        glDepthMask(GL_TRUE)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)

    def set_angle(self, x: float, y: float, z: float) -> None:
        self.rotation_x, self.rotation_y, self.rotation_z = x, y, z
        self.update()

    # Only orbit dragging and zoom; no FPS keys, nothing at all when not interactive

    def mousePressEvent(self, event):  # noqa: ANN001, N802
        if not self.interactive:
            event.ignore()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: ANN001, N802
        if not self.interactive:
            event.ignore()
            return
        super().mouseMoveEvent(event)

    def wheelEvent(self, event):  # noqa: ANN001, N802
        if not self.interactive:
            event.ignore()
            return
        self.zoom = max(-6.0, min(-1.0, self.zoom + event.angleDelta().y() / 480.0))
        self.update()

    def keyPressEvent(self, event):  # noqa: ANN001, N802
        event.ignore()

    def load_obj_data(self, obj_content: str) -> None:
        """Like Fleasion's loader, plus ``vt`` coordinates and ``v/vt/vn`` faces."""
        self._discard_mesh_display_list()
        cached = _PARSED.get(obj_content)
        if cached is not None:
            # Same model as another card or the studio: reuse the parsed lists (never mutated)
            self.vertices, self.colors, self.faces, self.normals, self.face_normals, self.uvs = cached
            self.needs_rebuild = True
            self.update()
            return
        self.vertices, self.colors, self.faces = [], [], []
        self.normals, self.face_normals, self.uvs = [], [], []
        for line in obj_content.splitlines():
            parts = line.split()
            if not parts or parts[0].startswith('#'):
                continue
            head = parts[0]
            if head == 'v':
                self.vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
                self.colors.append([1.0, 1.0, 1.0])
            elif head == 'vt':
                self.uvs.append([float(parts[1]), float(parts[2]) if len(parts) > 2 else 0.0])
            elif head == 'vn':
                self.normals.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif head == 'f':
                face_v: list[int] = []
                face_t: list[int] = []
                face_n: list[int] = []
                for part in parts[1:]:
                    indices = part.split('/')
                    face_v.append(int(indices[0]) - 1)
                    if len(indices) >= 2 and indices[1]:
                        face_t.append(int(indices[1]) - 1)
                    if len(indices) >= 3 and indices[2]:
                        face_n.append(int(indices[2]) - 1)
                # Fan-triangulate quads and polygons
                for i in range(1, len(face_v) - 1):
                    pick = (0, i, i + 1)
                    self.faces.append({
                        'v': [face_v[k] for k in pick],
                        't': [face_t[k] for k in pick] if len(face_t) == len(face_v) else [],
                        'n': [face_n[k] for k in pick] if len(face_n) == len(face_v) else [],
                    })
        if self.vertices:
            self._normalize_model()
            self._compute_face_normals()
        if len(_PARSED) >= _PARSED_LIMIT:
            _PARSED.pop(next(iter(_PARSED)))
        _PARSED[obj_content] = (self.vertices, self.colors, self.faces, self.normals, self.face_normals, self.uvs)
        self.needs_rebuild = True
        self.update()

    def _normalize_model(self) -> None:
        """Center on the bounding box (not the vertex average) so the model sits in the middle."""
        if not self.vertices:
            return
        vertices = np.array(self.vertices, dtype=float)
        vertices -= (vertices.min(axis=0) + vertices.max(axis=0)) / 2
        largest = np.abs(vertices).max()
        if largest > 0:
            vertices /= largest
        self.vertices = vertices.tolist()

    def set_texture(self, rgba: np.ndarray) -> None:
        """RGBA float array (0..1); uploaded on the next frame."""
        self._pending = np.ascontiguousarray(np.clip(rgba * 255.0 + 0.5, 0, 255).astype(np.uint8))
        self.update()

    def _upload_texture(self) -> None:
        data = self._pending
        if data is None:
            return
        self._pending = None
        created = not self._texture_id
        if created:
            self._texture_id = int(glGenTextures(1))
            glBindTexture(GL_TEXTURE_2D, self._texture_id)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glBindTexture(GL_TEXTURE_2D, self._texture_id)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        height, width = data.shape[:2]
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        try:
            glGenerateMipmap(GL_TEXTURE_2D)
        except Exception:  # noqa: BLE001 - very old drivers: fall back to plain filtering
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        if created:
            # The mesh was compiled without a texture; compile it again with one
            self.needs_rebuild = True

    def _paint_scene(self) -> None:
        self._upload_texture()
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        self._draw_background()
        glTranslatef(0.0, 0.0, self.zoom)
        glRotatef(self.rotation_y, 0.0, 1.0, 0.0)
        glRotatef(self.rotation_x, 1.0, 0.0, 0.0)
        glRotatef(self.rotation_z, 0.0, 0.0, 1.0)
        if self.vertices and self.faces:
            if self.needs_rebuild:
                self._build_display_list()
            if self.mesh_display_list != 0:
                glCallList(self.mesh_display_list)

    def _draw_axis_indicator(self) -> None:
        """No axis gizmo in the studio preview."""

    def _triangle_arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Per-corner positions, normals and texture coordinates of every triangle."""
        vertices = np.asarray(self.vertices, dtype=np.float32).reshape(-1, 3)
        count = len(vertices)
        faces = [face for face in self.faces if all(0 <= index < count for index in face['v'])]
        if not faces:
            empty = np.zeros((0, 3), dtype=np.float32)
            return empty, empty, np.zeros((0, 2), dtype=np.float32)
        corners = np.asarray([face['v'] for face in faces], dtype=np.int64)
        positions = np.ascontiguousarray(vertices[corners].reshape(-1, 3))
        # Normals: per corner when the OBJ has them, else the face normal
        face_normals = np.asarray(self.face_normals, dtype=np.float32).reshape(-1, 3)
        file_normals = np.asarray(self.normals, dtype=np.float32).reshape(-1, 3)
        normals = np.zeros((len(faces), 3, 3), dtype=np.float32)
        index_of = {id(face): i for i, face in enumerate(self.faces)}
        for row, face in enumerate(faces):
            n = face['n']
            if n and all(0 <= k < len(file_normals) for k in n):
                normals[row] = file_normals[n]
            else:
                original = index_of[id(face)]
                if original < len(face_normals):
                    normals[row] = face_normals[original]
        uvs = np.asarray(self.uvs, dtype=np.float32).reshape(-1, 2)
        texcoords = np.zeros((len(faces), 3, 2), dtype=np.float32)
        for row, face in enumerate(faces):
            tex = face.get('t', [])
            if tex and all(0 <= k < len(uvs) for k in tex):
                texcoords[row] = uvs[tex]
        # Image rows are uploaded top-first, so flip v
        texcoords[..., 1] = 1.0 - texcoords[..., 1]
        return (
            positions,
            np.ascontiguousarray(normals.reshape(-1, 3)),
            np.ascontiguousarray(texcoords.reshape(-1, 2)),
        )

    def _build_display_list(self) -> None:
        self._discard_mesh_display_list(make_current=False)
        self.mesh_display_list = glGenLists(1)
        glNewList(self.mesh_display_list, GL_COMPILE)
        textured = bool(self._texture_id and self.uvs)
        if textured:
            glEnable(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, self._texture_id)
            glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
        glColor3f(1.0, 1.0, 1.0)
        # One draw call from arrays instead of one Python call per vertex (much faster)
        positions, normals, texcoords = self._triangle_arrays()
        if len(positions):
            glEnableClientState(GL_VERTEX_ARRAY)
            glEnableClientState(GL_NORMAL_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, positions)
            glNormalPointer(GL_FLOAT, 0, normals)
            if textured:
                glEnableClientState(GL_TEXTURE_COORD_ARRAY)
                glTexCoordPointer(2, GL_FLOAT, 0, texcoords)
            glDrawArrays(GL_TRIANGLES, 0, len(positions))
            if textured:
                glDisableClientState(GL_TEXTURE_COORD_ARRAY)
            glDisableClientState(GL_NORMAL_ARRAY)
            glDisableClientState(GL_VERTEX_ARRAY)
        if textured:
            glDisable(GL_TEXTURE_2D)
        glEndList()
        self.needs_rebuild = False
