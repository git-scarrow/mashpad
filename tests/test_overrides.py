from pathlib import Path

import pytest

from mashpad.models import ManualOverride, OverrideTarget, Section, Track, TrackAnalysis
from mashpad.overrides import apply_override

BASE_ANALYSIS = TrackAnalysis(
    track=Track(path=Path("song.mp3")),
    bpm=140.0,
    key="C major",
    sections=(Section(label="verse", start_sec=10.0, end_sec=30.0, confidence=0.5),),
)


def test_bpm_override_corrects_an_octave_error():
    override = ManualOverride(target=OverrideTarget.BPM, reason="octave error", bpm_multiplier=0.5)
    corrected = apply_override(BASE_ANALYSIS, override)
    assert corrected.bpm == 70.0
    assert corrected.key == BASE_ANALYSIS.key  # untouched


def test_key_override_replaces_misclassified_key():
    override = ManualOverride(target=OverrideTarget.KEY, reason="modal ambiguity", key="G major")
    corrected = apply_override(BASE_ANALYSIS, override)
    assert corrected.key == "G major"
    assert corrected.bpm == BASE_ANALYSIS.bpm  # untouched


def test_phrase_boundary_override_shifts_all_sections():
    override = ManualOverride(
        target=OverrideTarget.PHRASE_BOUNDARY,
        reason="drifted boundary",
        phrase_boundary_shift_sec=-2.0,
    )
    corrected = apply_override(BASE_ANALYSIS, override)
    section = corrected.sections[0]
    assert section.start_sec == 8.0
    assert section.end_sec == 28.0


def test_phrase_boundary_override_does_not_go_negative():
    override = ManualOverride(
        target=OverrideTarget.PHRASE_BOUNDARY,
        reason="drifted boundary",
        phrase_boundary_shift_sec=-100.0,
    )
    corrected = apply_override(BASE_ANALYSIS, override)
    assert corrected.sections[0].start_sec == 0.0


def test_downbeat_override_not_yet_implemented():
    override = ManualOverride(
        target=OverrideTarget.DOWNBEAT, reason="phase shift", downbeat_shift_beats=1.0
    )
    with pytest.raises(NotImplementedError):
        apply_override(BASE_ANALYSIS, override)


def test_stem_gain_override_not_yet_implemented():
    override = ManualOverride(
        target=OverrideTarget.STEM_GAIN, reason="vocal bleed", stem="vocals", gain_db=-6.0
    )
    with pytest.raises(NotImplementedError):
        apply_override(BASE_ANALYSIS, override)


def test_bpm_override_requires_multiplier():
    override = ManualOverride(target=OverrideTarget.BPM, reason="missing param")
    with pytest.raises(ValueError):
        apply_override(BASE_ANALYSIS, override)
