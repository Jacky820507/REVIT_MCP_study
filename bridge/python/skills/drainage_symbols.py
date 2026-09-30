"""Read-only DXF symbol inventory. No nearest-text assignment or direction guessing.

Coordinates remain source WCS units: caller must calibrate against Revit circles.
DWG must be converted to a disposable DXF with an authorized converter first.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def classify(block_name, attributes, legend):
    """Only exact, documented project legend matches may classify a symbol."""
    rule = legend.get(block_name)
    if not rule or not rule.get("evidence"):
        return {"kind": "unknown", "direction": "unknown", "evidence": None}
    kind = rule.get("kind", "unknown")
    direction = rule.get("direction", "unknown")
    if kind not in ("head", "pipe", "unknown") or direction not in ("up", "down", "both", "unknown"):
        raise ValueError("Invalid legend kind/direction")
    tag = rule.get("directionAttribute")
    if tag:
        direction = rule.get("directionValues", {}).get(attributes.get(tag), "unknown")
        if direction not in ("up", "down", "both", "unknown"):
            raise ValueError("Invalid mapped direction")
    return {"kind": kind, "direction": direction, "evidence": rule["evidence"]}


def compatible(upper_direction, lower_direction):
    if "unknown" in (upper_direction, lower_direction):
        return None
    return upper_direction in ("down", "both") and lower_direction in ("up", "both")


def inventory(document, legend=None, limit=100000):
    from ezdxf.math import Matrix44
    result = {"unitsCode": document.header.get("$INSUNITS", 0), "coordinateSpace": "source-WCS-not-Revit", "blocks": [], "circles": [], "texts": [], "warnings": []}
    budget = [0]

    def visit(entities, transform, ancestry, inherited_layer="0", depth=0):
        if depth > 16:
            raise ValueError("Block nesting exceeds 16")
        for entity in entities:
            budget[0] += 1
            if budget[0] > limit:
                raise ValueError("Entity budget exceeded; no partial inventory returned")
            kind = entity.dxftype()
            layer = entity.dxf.get("layer", "0")
            layer = inherited_layer if layer == "0" else layer
            provenance = ancestry + [entity.dxf.get("handle", "virtual")]
            if kind == "INSERT":
                if entity.mcount > 1:
                    result["warnings"].append({"handles": provenance, "reason": "MINSERT unsupported"})
                    continue
                attrs = {a.dxf.tag: a.dxf.text for a in entity.attribs}
                result["blocks"].append({"name": entity.dxf.name, "handles": provenance, "layer": layer, "attributes": attrs, "classification": classify(entity.dxf.name, attrs, legend or {})})
                block = entity.block()
                if block is None:
                    result["warnings"].append({"handles": provenance, "reason": "missing block/xref"})
                    continue
                # ezdxf uses row vectors: local INSERT transform followed by parents.
                visit(block, entity.matrix44() @ transform, provenance, layer, depth + 1)
                visit(entity.attribs, transform, provenance, layer, depth + 1)
            elif kind == "CIRCLE":
                center = entity.ocs().to_wcs(entity.dxf.center)
                ocs = entity.ocs()
                x = transform.transform_direction(ocs.ux * entity.dxf.radius)
                y = transform.transform_direction(ocs.uy * entity.dxf.radius)
                if not math.isclose(x.magnitude, y.magnitude, rel_tol=1e-8) or abs(x.dot(y)) > 1e-8 * x.magnitude * y.magnitude:
                    result["warnings"].append({"handles": provenance, "reason": "nonuniform circle becomes ellipse"})
                    continue
                result["circles"].append({"handles": provenance, "layer": layer, "center": list(transform.transform(center)), "symbolRadius": x.magnitude, "normal": list(x.cross(y).normalize()), "classification": "unassigned"})
            elif kind in ("TEXT", "MTEXT", "ATTRIB"):
                text = entity.plain_text() if kind == "MTEXT" else entity.dxf.text
                position = entity.dxf.insert if kind == "MTEXT" else entity.ocs().to_wcs(entity.dxf.insert)
                result["texts"].append({"handles": provenance, "layer": layer, "text": text, "position": list(transform.transform(position)), "circleAssignment": None})
            elif kind in ("ARC", "LINE", "LWPOLYLINE", "POLYLINE", "HATCH", "SOLID"):
                # Retain presence for symbol review, do not pretend a circle is the whole symbol.
                result["warnings"].append({"handles": provenance, "layer": layer, "reason": "symbol_primitive_requires_review", "type": kind})
    visit(document.modelspace(), Matrix44(), [])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dxf")
    parser.add_argument("--legend", help="Project-confirmed JSON block rules; never inferred from generic names")
    args = parser.parse_args()
    path = Path(args.dxf)
    if path.suffix.lower() != ".dxf":
        parser.error("Read a DXF copy, not the original DWG")
    import ezdxf
    legend = json.loads(Path(args.legend).read_text(encoding="utf-8")) if args.legend else {}
    result = inventory(ezdxf.readfile(path), legend)
    result["sourceSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
