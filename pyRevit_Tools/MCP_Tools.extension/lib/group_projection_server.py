# -*- coding: utf-8 -*-
"""Snapshot-only group projection lines for Revit 2020 DirectContext3D.

The caller owns the persistent engine, view refresh and UI/event lifecycle.
Register/remove in a valid Revit API context. No transaction is required.
Graphics resources are created, validated and filled only in RenderScene.
"""
from __future__ import unicode_literals

import threading

from System import Guid
from pyrevit import DB
from pyrevit.api import DirectContext3D as dc3d
from pyrevit.api import ExternalService as es


# Reserved for this tool: rerunning it replaces only its own overlay.
SERVER_GUID = Guid("e1f76a28-60da-4c5f-a9b6-207cea593ab8")
MAX_SEGMENTS = 16000


def _id_value(value):
    if hasattr(value, "Value"):
        return int(value.Value)
    if hasattr(value, "IntegerValue"):
        return int(value.IntegerValue)
    return int(value)


class _LineBuffer(object):
    def __init__(self):
        self.vertex_buffer = None
        self.index_buffer = None
        self.vertex_format = None
        self.effect = None
        self.vertex_count = 0
        self.index_count = 0
        self.primitive_count = 0

    def is_valid(self):
        return all(resource is not None and resource.IsValid()
                   for resource in self._resources())

    def _resources(self):
        return (self.vertex_buffer, self.index_buffer,
                self.vertex_format, self.effect)

    def dispose(self):
        failures = []
        for name in ("vertex_buffer", "index_buffer", "vertex_format", "effect"):
            resource = getattr(self, name)
            if resource is not None:
                try:
                    resource.Dispose()
                    setattr(self, name, None)
                except Exception as exc:
                    failures.append(str(exc))
        if failures:
            raise RuntimeError("; ".join(failures))

    def build(self, segments):
        self.primitive_count = len(segments)
        self.vertex_count = self.primitive_count * 2
        self.index_count = self.primitive_count * 2
        float_capacity = self.vertex_count * dc3d.VertexPositionColored.GetSizeInFloats()
        index_capacity = self.primitive_count * dc3d.IndexLine.GetSizeInShortInts()
        bits = dc3d.VertexFormatBits.PositionColored
        self.vertex_format = dc3d.VertexFormat(bits)
        self.effect = dc3d.EffectInstance(bits)
        self.vertex_buffer = dc3d.VertexBuffer(float_capacity)
        self.index_buffer = dc3d.IndexBuffer(index_capacity)
        vertex_mapped = False
        index_mapped = False
        try:
            self.vertex_buffer.Map(float_capacity)
            vertex_mapped = True
            self.index_buffer.Map(index_capacity)
            index_mapped = True
            vertices = self.vertex_buffer.GetVertexStreamPositionColored()
            indices = self.index_buffer.GetIndexStreamLine()
            for idx, (a, b, rgb) in enumerate(segments):
                color = DB.ColorWithTransparency(rgb[0], rgb[1], rgb[2], 0)
                vertices.AddVertex(dc3d.VertexPositionColored(a, color))
                vertices.AddVertex(dc3d.VertexPositionColored(b, color))
                indices.AddLine(dc3d.IndexLine(idx * 2, idx * 2 + 1))
        finally:
            try:
                if index_mapped:
                    self.index_buffer.Unmap()
            finally:
                if vertex_mapped:
                    self.vertex_buffer.Unmap()

    def flush(self):
        dc3d.DrawContext.FlushBuffer(
            self.vertex_buffer, self.vertex_count,
            self.index_buffer, self.index_count,
            self.vertex_format, self.effect,
            dc3d.PrimitiveType.LineList, 0, self.primitive_count)


class ProjectionServer(dc3d.IDirectContext3DServer):
    """One document/view overlay; segments are (XYZ, XYZ, (r, g, b)).

    Construction does not register. add_server()/remove_server() return success
    and report failures through error. A replacement disables the prior instance;
    delayed removal of that prior instance cannot remove the replacement.
    """

    def __init__(self, doc, view_id, segments):
        self.doc = doc
        self.view_id = _id_value(view_id)
        self.enabled = True
        self.error = ""
        self.render_calls = 0
        self.matching_render_calls = 0
        self.flush_calls = 0
        self.clip_report = None
        self.bounding_box_calls = 0
        self.can_execute_calls = 0
        self._instance_id = Guid.NewGuid()
        self._lock = threading.RLock()
        self._buffers = []
        # Copy endpoints and RGB values: no mutable caller list or live geometry.
        self._segments = tuple(
            (DB.XYZ(a.X, a.Y, a.Z), DB.XYZ(b.X, b.Y, b.Z), tuple(rgb))
            for a, b, rgb in segments)
        self._bounds = None
        if self._segments:
            points = [point for a, b, unused in self._segments for point in (a, b)]
            self._bounds = (
                DB.XYZ(min(p.X for p in points), min(p.Y for p in points),
                       min(p.Z for p in points)),
                DB.XYZ(max(p.X for p in points), max(p.Y for p in points),
                       max(p.Z for p in points)))

    def GetServerId(self):
        return SERVER_GUID

    def GetServiceId(self):
        return es.ExternalServices.BuiltInExternalServices.DirectContext3DService

    def GetName(self):
        return "MCP Group Projection Overlay"

    def GetDescription(self):
        return "Snapshot group projection lines in one document and view"

    def GetVendorId(self):
        return "RevitMCP"

    def GetApplicationId(self):
        return ""

    def GetSourceId(self):
        return ""

    def UsesHandles(self):
        return False

    def UseInTransparentPass(self, view):
        return False

    def CanExecute(self, view):
        with self._lock:
            self.can_execute_calls += 1
        try:
            matched = bool(self.enabled and view is not None
                           and self.doc.IsValidObject and view.IsValidObject
                           and self.doc.Equals(view.Document)
                           and self.view_id == _id_value(view.Id))
            return matched
        except Exception:
            return False

    def GetBoundingBox(self, view):
        with self._lock:
            self.bounding_box_calls += 1
        if not self.enabled or self._bounds is None:
            return None
        if view is not None and not self.CanExecute(view):
            return None
        # The projected paths are coplanar. A zero-thickness Outline can be
        # rejected by Revit's visibility/culling before RenderScene is called.
        # Give the server a small 3D extent while keeping the actual vertices
        # exactly on the selected projection plane.
        pad = 10.0 / 304.8
        low, high = self._bounds
        return DB.Outline(DB.XYZ(low.X - pad, low.Y - pad, low.Z - pad),
                          DB.XYZ(high.X + pad, high.Y + pad, high.Z + pad))

    def _service(self):
        return es.ExternalServiceRegistry.GetService(self.GetServiceId())

    def _is_own_instance(self, server):
        return (server is self or
                getattr(server, "_instance_id", None) == self._instance_id)

    def _dispose_buffers(self):
        with self._lock:
            remaining = []
            failures = []
            for buffer in self._buffers:
                try:
                    buffer.dispose()
                except Exception as exc:
                    remaining.append(buffer)
                    failures.append(str(exc))
            self._buffers = remaining
            if failures:
                raise RuntimeError("; ".join(failures))

    def add_server(self):
        self.error = ""
        try:
            service = self._service()
            if service.IsRegisteredServerId(SERVER_GUID):
                previous = service.GetServer(SERVER_GUID)
                if not self._is_own_instance(previous):
                    if previous is not None and hasattr(previous, "enabled"):
                        previous.enabled = False
                    # Never dispose a server's resources before deregistration.
                    service.RemoveServer(SERVER_GUID)
                    if previous is not None and hasattr(previous, "_dispose_buffers"):
                        previous._dispose_buffers()
            if not service.IsRegisteredServerId(SERVER_GUID):
                service.AddServer(self)
            active = service.GetActiveServerIds()
            if not active.Contains(SERVER_GUID):
                active.Add(SERVER_GUID)
            service.SetActiveServers(active)
            self.enabled = True
            return True
        except Exception as exc:
            message = "add_server: " + str(exc)
            self.remove_server()
            self.error = message + ("; " + self.error if self.error else "")
            return False

    def remove_server(self):
        self.enabled = False
        self.error = ""
        try:
            service = self._service()
            if service.IsRegisteredServerId(SERVER_GUID):
                if self._is_own_instance(service.GetServer(SERVER_GUID)):
                    service.RemoveServer(SERVER_GUID)
            self._dispose_buffers()
            return True
        except Exception as exc:
            self.error = "remove_server: " + str(exc)
            return False

    def RenderScene(self, view, display_style):
        with self._lock:
            self.render_calls += 1
        with self._lock:
            if not self.CanExecute(view):
                return
            self.matching_render_calls += 1
            if not self._segments:
                return
            try:
                if self.clip_report is None:
                    try:
                        planes = dc3d.DrawContext.GetClipPlanes()
                        low, high = self._bounds
                        center = DB.XYZ((low.X + high.X) / 2.0,
                                        (low.Y + high.Y) / 2.0,
                                        (low.Z + high.Z) / 2.0)
                        bounds_corners = [
                            DB.XYZ(x, y, z)
                            for x in (low.X, high.X)
                            for y in (low.Y, high.Y)
                            for z in (low.Z, high.Z)]
                        details = []
                        for number, plane in enumerate(planes):
                            origin, normal = plane.Origin, plane.Normal
                            distances = [
                                ((point.X - origin.X) * normal.X +
                                 (point.Y - origin.Y) * normal.Y +
                                 (point.Z - origin.Z) * normal.Z) * 304.8
                                for point in bounds_corners]
                            center_distance = ((center.X - origin.X) * normal.X +
                                               (center.Y - origin.Y) * normal.Y +
                                               (center.Z - origin.Z) * normal.Z) * 304.8
                            details.append('{}: 法向 ({:.2f},{:.2f},{:.2f})，'
                                           '原點 Z {:.0f} mm，群組範圍距離 {:.0f}～{:.0f} mm，'
                                           '中心距 {:.0f} mm'.format(
                                               number + 1, normal.X, normal.Y, normal.Z,
                                               origin.Z * 304.8, min(distances),
                                               max(distances), center_distance))
                        self.clip_report = ('裁切平面 {} 個。'.format(len(details)) +
                                            ('\n' + '\n'.join(details) if details else ''))
                    except Exception as clip_exc:
                        self.clip_report = '無法讀取裁切平面：{}'.format(clip_exc)
                if dc3d.DrawContext.IsTransparentPass():
                    return
                dc3d.DrawContext.SetWorldTransform(DB.Transform.Identity)
                if not self._buffers or not all(b.is_valid() for b in self._buffers):
                    self._dispose_buffers()
                    for start in range(0, len(self._segments), MAX_SEGMENTS):
                        buffer = _LineBuffer()
                        # Track partial builds too, so failures cannot leak resources.
                        self._buffers.append(buffer)
                        buffer.build(self._segments[start:start + MAX_SEGMENTS])
                for buffer in self._buffers:
                    buffer.flush()
                    self.flush_calls += 1
                self.error = ""
            except Exception as exc:
                self.error = "RenderScene: " + str(exc)
                try:
                    self._dispose_buffers()
                except Exception as cleanup_exc:
                    self.error += "; cleanup: " + str(cleanup_exc)
