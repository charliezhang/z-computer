"""Z App Bundle (.zab): a zip with manifest.json, client.js, server.js, assets/."""
import io
import json
import zipfile
from pathlib import Path

PARTS = ("manifest.json", "client.js", "server.js")


def read_workspace(d: Path) -> dict:
    assets_dir = d / "assets"
    assets = {p.name: p.read_bytes() for p in sorted(assets_dir.glob("*")) if p.is_file()} if assets_dir.is_dir() else {}
    return {
        "manifest": json.loads((d / "manifest.json").read_text()),
        "client_js": (d / "client.js").read_text(),
        "server_js": (d / "server.js").read_text(),
        "assets": assets,
    }


def pack(d: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in PARTS:
            z.write(d / name, name)
        assets_dir = d / "assets"
        if assets_dir.is_dir():
            for p in sorted(assets_dir.glob("*")):
                if p.is_file():
                    z.write(p, f"assets/{p.name}")
    return buf.getvalue()


def read_bundle(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        return {
            "manifest": json.loads(z.read("manifest.json")),
            "client_js": z.read("client.js").decode(),
            "server_js": z.read("server.js").decode(),
            "assets": {n[len("assets/"):]: z.read(n) for n in names if n.startswith("assets/") and not n.endswith("/")},
        }


def unpack(data: bytes, d: Path) -> None:
    """Replace the workspace contents with the bundle's."""
    for name in PARTS:
        (d / name).unlink(missing_ok=True)
    assets_dir = d / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    for p in assets_dir.glob("*"):
        if p.is_file():
            p.unlink()
    b = read_bundle(data)
    (d / "manifest.json").write_text(json.dumps(b["manifest"], indent=2) + "\n")
    (d / "client.js").write_text(b["client_js"])
    (d / "server.js").write_text(b["server_js"])
    for name, blob in b["assets"].items():
        (assets_dir / name).write_bytes(blob)
