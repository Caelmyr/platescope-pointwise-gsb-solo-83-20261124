"""Reference association and explicit relative amount calculation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Match:
    sample: int
    reference: int | None
    distance: float | None


def lookup(samples, references, tolerance):
    matches = []
    for band in samples:
        nearest = min(references, key=lambda candidate: (abs(candidate.rf - band.rf), candidate.number), default=None)
        delta = abs(nearest.rf - band.rf) if nearest else None
        allowed = delta is not None and delta <= tolerance + 1e-12
        matches.append(Match(band.number, nearest.number if allowed else None, delta))
    return matches


def relative_amount(samples, references, sample_number, reference_number):
    sample = next((band for band in samples if band.number == sample_number), None)
    reference = next((band for band in references if band.number == reference_number), None)
    percentage = None
    if sample is not None and reference is not None and reference.amount > 0:
        percentage = sample.amount / reference.amount * 100
    return sample, reference, percentage
