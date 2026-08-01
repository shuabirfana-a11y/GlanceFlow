from __future__ import annotations

from dataclasses import dataclass

from glanceflow.domain.models import EvidenceLine


@dataclass(frozen=True)
class EvidenceRow:
    lines: tuple[EvidenceLine, ...]

    @property
    def text(self) -> str:
        return " ".join(line.text.strip() for line in self.lines if line.text.strip())

    @property
    def line_ids(self) -> list[str]:
        return [line.line_id for line in self.lines]

    @property
    def confidence(self) -> float:
        return min((line.confidence for line in self.lines), default=0.0)


def _center_y(line: EvidenceLine) -> float:
    assert line.bbox is not None
    return (line.bbox[1] + line.bbox[3]) / 2


def _height(line: EvidenceLine) -> float:
    assert line.bbox is not None
    return max(1.0, line.bbox[3] - line.bbox[1])


def group_visual_rows(lines: list[EvidenceLine]) -> list[EvidenceRow]:
    """Group OCR fragments sharing a visual row without inventing evidence."""
    positioned = [line for line in lines if line.bbox is not None]
    positioned.sort(key=lambda line: (_center_y(line), line.bbox[0]))
    groups: list[list[EvidenceLine]] = []
    for line in positioned:
        if not groups:
            groups.append([line])
            continue
        current = groups[-1]
        center = sum(_center_y(item) for item in current) / len(current)
        tolerance = max(16.0, max(_height(item) for item in [*current, line]) * 0.65)
        if abs(_center_y(line) - center) <= tolerance:
            current.append(line)
        else:
            groups.append([line])
    rows = []
    for group in groups:
        group.sort(key=lambda line: line.bbox[0] if line.bbox else 0)
        rows.append(EvidenceRow(tuple(group)))
    return rows


def validate_evidence_links(ocr_result, line_ids: list[str]) -> bool:
    known = {line.line_id for line in ocr_result.evidence_lines}
    return bool(line_ids) and all(line_id in known for line_id in line_ids)

