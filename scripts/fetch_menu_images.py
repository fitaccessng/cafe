"""Fetch curated, openly licensed menu photos and write a verified manifest."""

import json
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "app" / "static" / "images" / "menu"
SOURCE_FILE = IMAGE_DIR / "image-sources.json"
MANIFEST_FILE = IMAGE_DIR / "image-manifest.json"
ALLOWED_LICENSES = {"CC0", "Public domain", "CC BY 2.0", "CC BY 2.5", "CC BY 3.0", "CC BY 4.0", "CC BY-SA 2.0", "CC BY-SA 3.0", "CC BY-SA 4.0"}


def has_image_signature(data):
    return data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n") or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def main():
    sources = json.loads(SOURCE_FILE.read_text(encoding="utf-8"))
    try:
        manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {"version": 1, "image_license_policy": "Wikimedia Commons image with source page, creator and license metadata; downloadable files are retained locally.", "images": {}}
    images = manifest.setdefault("images", {})
    downloaded = []
    unchanged = []
    failed = []
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    for slug, record in sources.items():
        if record["license"] not in ALLOWED_LICENSES or not record.get("creator"):
            failed.append((slug, "missing or unsupported attribution/license"))
            continue
        filename = f"{slug}.jpg"
        target = IMAGE_DIR / filename
        verified = images.get(slug, {})
        if target.exists() and has_image_signature(target.read_bytes()[:16]) and all(verified.get(key) for key in ("creator", "license", "source_page")):
            unchanged.append(slug)
            continue

        url = f"https://upload.wikimedia.org/wikipedia/commons/thumb/{record['path']}/960px-{record['path'].split('/', 2)[-1]}"
        request = Request(url, headers={"User-Agent": "CafeCoffeeDayCatalogue/1.0 (image downloader; contact via repository README)"})
        try:
            with urlopen(request, timeout=30) as response:
                content_type = response.headers.get_content_type()
                content = response.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024 or not content_type.startswith("image/") or not has_image_signature(content[:16]):
                failed.append((slug, f"invalid response: {content_type}, {len(content)} bytes"))
                continue
            with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            result = subprocess.run(
                ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "78", "-Z", "1000", str(temporary_path), "--out", str(target)],
                capture_output=True, text=True, check=False,
            )
            temporary_path.unlink(missing_ok=True)
            if result.returncode != 0 or not target.exists() or not has_image_signature(target.read_bytes()[:16]):
                target.unlink(missing_ok=True)
                failed.append((slug, "image conversion failed"))
                continue
            images[slug] = {
                "file": filename,
                "source_page": f"https://commons.wikimedia.org/wiki/File:{record['title'].replace(' ', '_')}",
                "source_url": url,
                "creator": record["creator"],
                "license": record["license"],
                "alt": f"Illustrative stock photograph: {record['title'].removesuffix('.jpg').removesuffix('.png')}. This may differ from the café's actual product.",
            }
            downloaded.append(slug)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            failed.append((slug, f"download failed: {type(error).__name__}: {error}"))

    manifest_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=IMAGE_DIR, suffix=".json", delete=False)
    try:
        json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)
        manifest_file.write("\n")
        manifest_file.close()
        Path(manifest_file.name).replace(MANIFEST_FILE)
    except Exception:
        Path(manifest_file.name).unlink(missing_ok=True)
        raise

    print(f"Downloaded and verified: {len(downloaded)} ({', '.join(downloaded)})")
    print(f"Already verified locally: {len(unchanged)} ({', '.join(unchanged)})")
    print(f"Unavailable/rejected: {len(failed)}")
    for slug, reason in failed:
        print(f"  {slug}: {reason}")
    print(f"Manifest: {MANIFEST_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
