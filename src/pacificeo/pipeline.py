import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PipelineResult:
    asset_href: str
    validation: dict[str, Any] | None


class ExternalScienceAdapter:
    """Stable manifest contract around the existing modelling stack."""

    def run(self, manifest: dict[str, Any]) -> PipelineResult:
        with tempfile.TemporaryDirectory(prefix="pacificeo-") as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            output_path = root / "result.json"
            manifest["result_path"] = str(output_path)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            command = os.environ.get("PACIFICEO_PIPELINE_COMMAND")
            if not command:
                raise RuntimeError("PACIFICEO_PIPELINE_COMMAND is not configured")
            args = [*shlex.split(command, posix=os.name != "nt"), str(manifest_path)]
            subprocess.run(args, check=True, timeout=7200)
            if not output_path.is_file():
                raise RuntimeError("Science adapter did not write result.json")
            result = json.loads(output_path.read_text(encoding="utf-8"))
            if not result.get("asset_href"):
                raise RuntimeError("Science adapter result is missing asset_href")
            return PipelineResult(result["asset_href"], result.get("validation"))


def normalize_validation(raw: dict[str, Any] | None, metric: str, minimum_pixels: int) -> dict[str, Any] | None:
    if raw is None:
        return None
    if raw.get("metric") != metric:
        raise ValueError(f"Expected validation metric {metric!r}")
    count, value = int(raw.get("reference_pixels", 0)), raw.get("value")
    if count < minimum_pixels or value is None:
        return None
    value = float(value)
    if not 0 <= value <= 1:
        raise ValueError("Validation metric must be in [0, 1]")
    return {"metric": metric, "value": value, "reference_pixels": count}
