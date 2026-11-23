"""Order-preserving one-to-one reference association and relative amount calculation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Match:
    sample: int
    reference: int | None
    distance: float | None


@dataclass(frozen=True)
class Suggestion:
    strategy: str
    rationale: str
    pairs: tuple
    total_distance: float
    max_distance: float


def _eligible(samples, references, tolerance):
    allowed = {}
    for index, band in enumerate(samples):
        for other, candidate in enumerate(references):
            distance = abs(candidate.rf - band.rf)
            if distance <= tolerance + 1e-12:
                allowed[(index, other)] = distance
    return allowed


def _grid(samples, references, allowed, cap=None):
    """Sequence-alignment DP: most pairs, then smallest total, then smallest worst."""
    n, m = len(samples), len(references)
    grid = [[(0, 0.0, 0.0)] * (m + 1) for _ in range(n + 1)]

    def better(candidate, best):
        count, total, worst = candidate
        base_count, base_total, base_worst = best
        if count != base_count:
            return count > base_count
        if total != base_total:
            return total < base_total
        return worst < base_worst

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best = grid[i - 1][j]
            if better(grid[i][j - 1], best):
                best = grid[i][j - 1]
            distance = allowed.get((i - 1, j - 1))
            if distance is not None and (cap is None or distance <= cap + 1e-12):
                count, total, worst = grid[i - 1][j - 1]
                paired = (count + 1, total + distance, max(worst, distance))
                if better(paired, best):
                    best = paired
            grid[i][j] = best
    return grid


def _same_state(left, right):
    return left[0] == right[0] and abs(left[1] - right[1]) <= 1e-12 and abs(left[2] - right[2]) <= 1e-12


def _trace(grid, samples, references, allowed, cap):
    chain = []
    i, j = len(samples), len(references)
    while i > 0 and j > 0:
        distance = allowed.get((i - 1, j - 1))
        if distance is not None and (cap is None or distance <= cap + 1e-12):
            count, total, worst = grid[i - 1][j - 1]
            paired = (count + 1, total + distance, max(worst, distance))
        else:
            paired = None
        if paired is not None and _same_state(paired, grid[i][j]):
            chain.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif _same_state(grid[i - 1][j], grid[i][j]):
            i -= 1
        elif _same_state(grid[i][j - 1], grid[i][j]):
            j -= 1
        else:  # pragma: no cover - every cell state has a valid predecessor
            break
    chain.reverse()
    return chain


def _best_chain(samples, references, allowed, minimize_worst):
    """Maximum-cardinality chain of non-crossing, once-only tolerance pairs.

    The balanced strategy breaks cardinality ties on total |ΔRf|; its cost is
    additive so one DP pass is exact. The cautious strategy minimizes the
    largest single |ΔRf| first, which is not separable cell by cell: find the
    smallest distance cap that still admits the maximum pair count, then take
    the smallest-total chain under that cap.
    """
    if not allowed:
        return []
    if not minimize_worst:
        grid = _grid(samples, references, allowed)
        return _trace(grid, samples, references, allowed, None)

    full = _grid(samples, references, allowed)
    target_count = full[len(samples)][len(references)][0]
    caps = sorted(set(allowed.values()))
    lo, hi = 0, len(caps) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        probe = _grid(samples, references, allowed, caps[mid])
        if probe[len(samples)][len(references)][0] >= target_count:
            hi = mid
        else:
            lo = mid + 1
    cap = caps[lo]
    grid = _grid(samples, references, allowed, cap)
    chain = _trace(grid, samples, references, allowed, cap)
    assert len(chain) == target_count
    return chain


def _suggestion(strategy, rationale, chain, samples, references):
    pairs = tuple({"sample": samples[i].number, "reference": references[j].number,
                   "distance": round(abs(references[j].rf - samples[i].rf), 6)}
                  for i, j in chain)
    total = round(sum(pair["distance"] for pair in pairs), 6)
    worst = round(max((pair["distance"] for pair in pairs), default=0.0), 6)
    return Suggestion(strategy, rationale, pairs, total, worst)


def lookup(samples, references, tolerance):
    """Nearest-neighbour rows plus adoptable one-to-one order-preserving associations."""
    allowed = _eligible(samples, references, tolerance)
    balanced_chain = _best_chain(samples, references, allowed, False)
    cautious_chain = _best_chain(samples, references, allowed, True)

    balanced = _suggestion(
        "balanced", "在认定条数相同的方案中，整组 |ΔRf| 合计最小，各带分担偏差。",
        balanced_chain, samples, references)
    cautious = _suggestion(
        "cautious", "在认定条数相同的方案中，最偏一条的 |ΔRf| 最小，避免单条勉强配对。",
        cautious_chain, samples, references)

    suggestions = [balanced]
    if cautious.pairs != balanced.pairs:
        # Lead with the plan whose worst single pairing is less extreme.
        if cautious.max_distance < balanced.max_distance - 1e-12:
            suggestions.insert(0, cautious)
        else:
            suggestions = [cautious, balanced]
    chosen = {pair["sample"]: pair["reference"] for pair in suggestions[0].pairs}

    matches = []
    for band in samples:
        nearest = min(references,
                      key=lambda candidate: (abs(candidate.rf - band.rf), candidate.number),
                      default=None)
        delta = abs(nearest.rf - band.rf) if nearest else None
        matches.append(Match(band.number, chosen.get(band.number), delta))
    return matches, suggestions


def adoption_key(settings):
    """Settings that can change which bands exist or where they migrate."""
    fields = ("lane", "reference", "tolerance", "roi", "front", "origin", "lanes",
              "channel", "cutoff", "min_height")
    return {name: _freeze(settings.get(name)) for name in fields}


def _freeze(value):
    if isinstance(value, list):
        return [_freeze(item) for item in value]
    return value


def relative_amount(samples, references, sample_number, reference_number):
    sample = next((band for band in samples if band.number == sample_number), None)
    reference = next((band for band in references if band.number == reference_number), None)
    percentage = None
    if sample is not None and reference is not None and reference.amount > 0:
        percentage = sample.amount / reference.amount * 100
    return sample, reference, percentage
