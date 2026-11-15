import numpy as np
import pytest

from app.services.difference import DifferenceImageError, compare_aligned_images


def test_difference_masks_non_overlapping_pixels_and_finds_injected_change():
    rng = np.random.default_rng(12)
    reference = rng.normal(0, 1, (40, 40))
    target = rng.normal(0, 1, (40, 40))
    target[8, 12] += 20.0
    reference[0, 0] = np.nan

    result = compare_aligned_images(reference, target, sigma_threshold=5)

    assert result["status"] == "completed"
    assert not result["valid_mask"][0, 0]
    assert np.isnan(result["difference"][0, 0])
    assert any(item["x"] == 12 and item["y"] == 8 for item in result["candidates"])


def test_difference_is_target_minus_reference():
    reference = np.full((4, 4), 3.0)
    target = np.full((4, 4), 5.0)
    target[0, 0] = 9.0

    result = compare_aligned_images(reference, target)

    assert result["difference"][1, 1] == pytest.approx(2.0)
    assert result["background_offset"] == pytest.approx(2.0)


def test_difference_rejects_different_shapes():
    with pytest.raises(DifferenceImageError, match="identical shapes"):
        compare_aligned_images(np.zeros((4, 4)), np.zeros((5, 4)))


def test_difference_rejects_insufficient_overlap():
    reference = np.full((2, 2), np.nan)
    target = np.ones((2, 2))
    with pytest.raises(DifferenceImageError, match="three overlapping"):
        compare_aligned_images(reference, target)


def test_constant_difference_does_not_report_false_candidates():
    reference = np.zeros((8, 8))
    target = np.full((8, 8), 7.0)

    result = compare_aligned_images(reference, target)

    assert result["background_offset"] == pytest.approx(7.0)
    assert result["candidate_count"] == 0
    assert result["status"] == "no_resolvable_residual_scatter"


def test_candidate_output_is_capped():
    rng = np.random.default_rng(8)
    reference = np.zeros((20, 20))
    target = rng.normal(0, 0.1, (20, 20))
    target[::2, ::2] += 10.0

    result = compare_aligned_images(reference, target, max_candidates=3)

    assert result["candidate_count"] == 100
    assert len(result["candidates"]) == 3
