from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen

from glanceflow.evaluation.public_web import load_manifest


def main() -> int:
    rows = load_manifest()
    for row in rows:
        target = Path(row.local_cache_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        request = Request(row.image_url, headers={"User-Agent": "GlanceFlow-Stage8-Validation/1.0"})
        with urlopen(request, timeout=30) as response:  # no authentication or access-control bypass
            target.write_bytes(response.read())
        print(f"cached {row.sample_id}: {target}")
    print("Download complete. Do not change privacy_reviewed or annotation_status until manual visual review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
