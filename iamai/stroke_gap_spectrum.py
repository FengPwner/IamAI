"""stroke_gap_spectrum — analyse the frequency distribution of inter-stroke gaps.

An auto-writer with a fixed cadence should produce gaps clustered around
one value.  Real systems drift: sometimes the gap is 15s, sometimes 60s,
sometimes 600s.  This module bins gaps into logarithmic frequency bands
and computes spectral metrics to characterise the timing behaviour.

A **gap** is the time difference between consecutive strokes.  Gaps are
assigned to logarithmic bins: [0-10s), [10-30s), [30-60s), [60-300s),
[300-900s), [900-3600s), [3600s+).  The resulting histogram reveals
whether the writer maintains its target cadence or drifts across scales.

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
total_strokes             total strokes analysed
total_gaps                number of inter-stroke gaps
bin_counts                dict mapping bin label to count
bin_fractions             dict mapping bin label to fraction (0-1)
dominant_bin              bin with highest count
dominant_fraction         fraction of gaps in dominant bin
spectral_entropy          Shannon entropy of bin distribution (bits)
spectral_uniformity       0-1; 1 = perfectly uniform across bins
cadence_adherence         fraction of gaps within ±50% of target cadence
mean_gap                  mean gap in seconds
median_gap                median gap in seconds
========================  =============================================

Interpretation
--------------

* **spectral_entropy < 1.5** — highly concentrated (one dominant scale)
* **spectral_entropy 1.5–2.5** — moderate spread (2-3 scales active)
* **spectral_entropy > 2.5** — dispersed across many time scales

* **cadence_adherence > 0.80** — writer tracks target well
* **cadence_adherence 0.50–0.80** — occasional drift
* **cadence_adherence < 0.50** — poor cadence tracking

Edge cases
----------

* Fewer than 2 strokes → zeroed report.
* All gaps identical → entropy = 0, uniformity = 1.
* Negative gaps are skipped.

Written by Qwen during caretaker visit 721, 2026-11-19.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Logarithmic bin boundaries (seconds)
DEFAULT_BIN_EDGES = [0, 10, 30, 60, 300, 900, 3600, float('inf')]
DEFAULT_BIN_LABELS = ['0-10s', '10-30s', '30-60s', '1-5min', '5-15min', '15-60min', '60min+']
DEFAULT_TARGET_CADENCE = 15.0  # seconds


@dataclass
class GapSpectrumReport:
    """Result of gap spectrum analysis."""
    
    total_strokes: int = 0
    total_gaps: int = 0
    bin_counts: Dict[str, int] = field(default_factory=dict)
    bin_fractions: Dict[str, float] = field(default_factory=dict)
    dominant_bin: str = ""
    dominant_fraction: float = 0.0
    spectral_entropy: float = 0.0
    spectral_uniformity: float = 0.0
    cadence_adherence: float = 0.0
    mean_gap: float = 0.0
    median_gap: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialise to plain dict."""
        return {
            'total_strokes': self.total_strokes,
            'total_gaps': self.total_gaps,
            'bin_counts': self.bin_counts,
            'bin_fractions': self.bin_fractions,
            'dominant_bin': self.dominant_bin,
            'dominant_fraction': self.dominant_fraction,
            'spectral_entropy': self.spectral_entropy,
            'spectral_uniformity': self.spectral_uniformity,
            'cadence_adherence': self.cadence_adherence,
            'mean_gap': self.mean_gap,
            'median_gap': self.median_gap,
        }
    
    def classify(self) -> Dict[str, str]:
        """Classify spectral characteristics."""
        # Spectral entropy classification
        if self.spectral_entropy < 1.5:
            concentration = 'concentrated'
        elif self.spectral_entropy < 2.5:
            concentration = 'moderate_spread'
        else:
            concentration = 'dispersed'
        
        # Cadence adherence classification
        if self.cadence_adherence > 0.80:
            tracking = 'excellent'
        elif self.cadence_adherence > 0.50:
            tracking = 'moderate'
        else:
            tracking = 'poor'
        
        return {
            'concentration': concentration,
            'tracking': tracking,
        }


def _extract_timestamps(strokes: Sequence[dict]) -> List[float]:
    """Extract numeric timestamps from stroke records."""
    timestamps = []
    for s in strokes:
        if 'ts' in s:
            timestamps.append(float(s['ts']))
        elif 'at' in s:
            # Parse ISO format
            from datetime import datetime
            dt = datetime.fromisoformat(s['at'])
            timestamps.append(dt.timestamp())
    return timestamps


def _compute_gaps(timestamps: Sequence[float]) -> List[float]:
    """Compute positive inter-stroke gaps."""
    gaps = []
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if gap > 0:
            gaps.append(gap)
    return gaps


def _assign_bin(gap: float, edges: Sequence[float], labels: Sequence[str]) -> str:
    """Assign a gap to its logarithmic bin."""
    for i in range(len(edges) - 1):
        if edges[i] <= gap < edges[i + 1]:
            return labels[i]
    return labels[-1]


def _spectral_entropy(bin_fractions: Dict[str, float]) -> float:
    """Compute Shannon entropy of bin distribution in bits."""
    entropy = 0.0
    for frac in bin_fractions.values():
        if frac > 0:
            entropy -= frac * math.log2(frac)
    return entropy


def _spectral_uniformity(bin_fractions: Dict[str, float]) -> float:
    """Compute how uniform the distribution is (0-1)."""
    if not bin_fractions:
        return 0.0
    
    n = len(bin_fractions)
    if n == 0:
        return 0.0
    
    # Compare to uniform distribution
    uniform_frac = 1.0 / n
    max_deviation = sum(abs(frac - uniform_frac) for frac in bin_fractions.values())
    # Normalise: max possible deviation is 2.0 (all in one bin)
    uniformity = 1.0 - (max_deviation / 2.0)
    return max(0.0, min(1.0, uniformity))


def _cadence_adherence(gaps: Sequence[float], target: float, tolerance: float = 0.5) -> float:
    """Fraction of gaps within ±tolerance of target cadence."""
    if not gaps:
        return 0.0
    
    lower = target * (1.0 - tolerance)
    upper = target * (1.0 + tolerance)
    within = sum(1 for g in gaps if lower <= g <= upper)
    return within / len(gaps)


def analyse_gap_spectrum(
    strokes: Sequence[dict],
    bin_edges: Optional[Sequence[float]] = None,
    bin_labels: Optional[Sequence[str]] = None,
    target_cadence: float = DEFAULT_TARGET_CADENCE,
) -> GapSpectrumReport:
    """Analyse the frequency distribution of inter-stroke gaps.
    
    Parameters
    ----------
    strokes : sequence of stroke dicts
        Stroke records with 'ts' or 'at' timestamp fields.
    bin_edges : sequence of floats, optional
        Bin boundary values in seconds. Defaults to logarithmic scale.
    bin_labels : sequence of strings, optional
        Labels for each bin. Must have len(bin_edges) - 1 elements.
    target_cadence : float
        Expected inter-stroke gap in seconds.
    
    Returns
    -------
    GapSpectrumReport
        Analysis results.
    """
    if bin_edges is None:
        bin_edges = DEFAULT_BIN_EDGES
    if bin_labels is None:
        bin_labels = DEFAULT_BIN_LABELS
    
    # Validate
    if len(bin_labels) != len(bin_edges) - 1:
        raise ValueError(f"bin_labels must have {len(bin_edges) - 1} elements, got {len(bin_labels)}")
    
    timestamps = _extract_timestamps(strokes)
    gaps = _compute_gaps(timestamps)
    
    if len(gaps) == 0:
        return GapSpectrumReport(total_strokes=len(strokes))
    
    # Initialise bin counts
    bin_counts = {label: 0 for label in bin_labels}
    
    # Assign gaps to bins
    for gap in gaps:
        bin_label = _assign_bin(gap, bin_edges, bin_labels)
        bin_counts[bin_label] += 1
    
    # Compute fractions
    total_gaps = len(gaps)
    bin_fractions = {label: count / total_gaps for label, count in bin_counts.items()}
    
    # Find dominant bin
    dominant_bin = max(bin_counts, key=bin_counts.get)
    dominant_fraction = bin_counts[dominant_bin] / total_gaps
    
    # Compute spectral metrics
    entropy = _spectral_entropy(bin_fractions)
    uniformity = _spectral_uniformity(bin_fractions)
    
    # Compute cadence adherence
    adherence = _cadence_adherence(gaps, target_cadence)
    
    # Compute gap statistics
    mean_gap = statistics.mean(gaps) if gaps else 0.0
    median_gap = statistics.median(gaps) if gaps else 0.0
    
    return GapSpectrumReport(
        total_strokes=len(strokes),
        total_gaps=total_gaps,
        bin_counts=bin_counts,
        bin_fractions=bin_fractions,
        dominant_bin=dominant_bin,
        dominant_fraction=dominant_fraction,
        spectral_entropy=entropy,
        spectral_uniformity=uniformity,
        cadence_adherence=adherence,
        mean_gap=mean_gap,
        median_gap=median_gap,
    )


def analyse_strokes_file(
    path: Path,
    bin_edges: Optional[Sequence[float]] = None,
    bin_labels: Optional[Sequence[str]] = None,
    target_cadence: float = DEFAULT_TARGET_CADENCE,
) -> GapSpectrumReport:
    """Analyse gap spectrum from a JSONL strokes file."""
    strokes = []
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if line:
                strokes.append(json.loads(line))
    
    return analyse_gap_spectrum(strokes, bin_edges, bin_labels, target_cadence)


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python stroke_gap_spectrum.py <strokes.jsonl> [target_cadence_sec]")
        sys.exit(1)
    
    path = Path(sys.argv[1])
    target = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TARGET_CADENCE
    
    report = analyse_strokes_file(path, target_cadence=target)
    
    print(f"Total strokes: {report.total_strokes}")
    print(f"Total gaps: {report.total_gaps}")
    print(f"Mean gap: {report.mean_gap:.1f}s")
    print(f"Median gap: {report.median_gap:.1f}s")
    print(f"\nBin distribution:")
    for label, frac in sorted(report.bin_fractions.items()):
        count = report.bin_counts[label]
        print(f"  {label:12s}: {count:5d} ({frac:.1%})")
    print(f"\nDominant bin: {report.dominant_bin} ({report.dominant_fraction:.1%})")
    print(f"Spectral entropy: {report.spectral_entropy:.2f} bits")
    print(f"Spectral uniformity: {report.spectral_uniformity:.2f}")
    print(f"Cadence adherence: {report.cadence_adherence:.1%}")
    print(f"\nClassification: {report.classify()}")
