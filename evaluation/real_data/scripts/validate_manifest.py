from __future__ import annotations

import json

from glanceflow.evaluation.real_data import validate_real_dataset


if __name__ == "__main__":
    samples = validate_real_dataset()
    print(json.dumps({"status": "VALID", "real_sample_count": len(samples)}, ensure_ascii=False))
