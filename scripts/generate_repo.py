#!/usr/bin/env python3
"""Builds repo/render_to_mp4.zip and repo/index.json for this Blender
Extensions repository.

This intentionally does NOT call Blender's own
`blender --command extension server-generate` to avoid a dependency on
having Blender (or a third-party action that installs it) available in
CI. The index.json schema is small and documented, so we produce it
directly:
https://developer.blender.org/docs/features/extensions/api_listing/v1/

Requires Python 3.11+ for the standard-library `tomllib` module.
"""
import hashlib
import json
import os
import tomllib
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTENSION_DIR = os.path.join(ROOT, "render_to_mp4")
REPO_DIR = os.path.join(ROOT, "repo")
MANIFEST_PATH = os.path.join(EXTENSION_DIR, "blender_manifest.toml")

# Update this if the repo is ever renamed or moved to a different account.
RAW_BASE_URL = "https://raw.githubusercontent.com/LucianoVallejo/blender-render-to-mp4/main"


def build_zip(extension_id: str) -> str:
    os.makedirs(REPO_DIR, exist_ok=True)
    zip_path = os.path.join(REPO_DIR, f"{extension_id}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirnames, filenames in os.walk(EXTENSION_DIR):
            for filename in filenames:
                if filename.startswith("."):
                    continue
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, EXTENSION_DIR)
                zf.write(full_path, rel_path)

    return zip_path


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def main() -> None:
    with open(MANIFEST_PATH, "rb") as f:
        manifest = tomllib.load(f)

    zip_path = build_zip(manifest["id"])
    zip_name = os.path.basename(zip_path)

    entry = {
        "id": manifest["id"],
        "name": manifest["name"],
        "tagline": manifest["tagline"],
        "version": manifest["version"],
        "type": manifest["type"],
        "archive_size": os.path.getsize(zip_path),
        "archive_hash": sha256_of(zip_path),
        "archive_url": f"{RAW_BASE_URL}/repo/{zip_name}",
        "blender_version_min": manifest["blender_version_min"],
        "maintainer": manifest["maintainer"],
        "tags": manifest.get("tags", []),
        "license": manifest["license"],
        "website": manifest.get("website", ""),
        "schema_version": manifest["schema_version"],
    }

    index = {
        "version": "v1",
        "blocklist": [],
        "data": [entry],
    }

    index_path = os.path.join(REPO_DIR, "index.json")
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)
        f.write("\n")

    print(f"Wrote {zip_path} ({entry['archive_size']} bytes)")
    print(f"Wrote {index_path}")


if __name__ == "__main__":
    main()
