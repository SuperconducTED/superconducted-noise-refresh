"""The scoring of readout calibrations against device counts, on constructed inputs."""

from __future__ import annotations

import numpy as np
import pytest
from qiskit_aer import AerSimulator

from noise_refresh.hardware import (
    VERDICTS,
    Share,
    confirmed_share,
    contrast,
    marginal_ones,
    measured_assignment,
    prepared_values_read,
    reading_change,
    readout_circuits,
    sums_by_day,
    symmetric_offset,
    usable,
    verdict,
)


def test_the_two_circuits_measure_the_named_qubits_in_order() -> None:
    qubits = (5, 1, 7)
    zeros, ones = readout_circuits(qubits, device_qubits=9)
    assert zeros.num_qubits == ones.num_qubits == 9
    assert zeros.count_ops() == {"measure": 3}
    assert ones.count_ops() == {"x": 3, "measure": 3}
    flipped = [ones.find_bit(i.qubits[0]).index for i in ones.data if i.operation.name == "x"]
    assert sorted(flipped) == [1, 5, 7]
    measured = [
        (zeros.find_bit(i.qubits[0]).index, zeros.find_bit(i.clbits[0]).index)
        for i in zeros.data
        if i.operation.name == "measure"
    ]
    assert measured == [(5, 0), (1, 1), (7, 2)]
    with pytest.raises(ValueError, match="distinct"):
        readout_circuits((1, 1), device_qubits=9)
    with pytest.raises(ValueError, match="below 9"):
        readout_circuits((1, 9), device_qubits=9)


def test_ideal_counts_of_the_two_circuits_give_no_assignment_error() -> None:
    # End to end without noise: circuits, simulator, bit order, measured assignment.
    zeros, ones = readout_circuits((5, 1, 7), device_qubits=9)
    counts = AerSimulator().run([zeros, ones], shots=200).result().get_counts()
    assert counts == [{"000": 200}, {"111": 200}]
    assert np.array_equal(measured_assignment(counts[0], counts[1], 3), np.zeros((3, 2)))
    assert prepared_values_read(counts[0], counts[1], 3)


def test_the_validity_check_catches_a_qubit_that_was_not_flipped() -> None:
    zeros = {"000": 100}
    assert prepared_values_read(zeros, {"111": 95, "110": 5}, 3)
    # Bit 1 reads 0 in every shot of the circuit that should have flipped it.
    assert not prepared_values_read(zeros, {"101": 100}, 3)
    # A circuit that leaves qubits in 0 and reads mostly 1 fails too.
    assert not prepared_values_read({"001": 60, "000": 40}, {"111": 100}, 3)


def test_marginals_follow_qiskit_bit_order() -> None:
    # Bit 0 is the rightmost character: "001" has bit 0 set.
    ones = marginal_ones({"001": 30, "100": 10, "000": 60}, 3)
    assert ones.tolist() == [0.3, 0.0, 0.1]
    with pytest.raises(ValueError, match="does not have 3 bits"):
        marginal_ones({"01": 1}, 3)
    with pytest.raises(ValueError, match="no shots"):
        marginal_ones({}, 3)


def test_measured_assignment_reads_each_direction_from_its_circuit() -> None:
    zeros = {"00": 90, "01": 10}  # qubit 0 reads 1 in 10% of the shots that prepared 0
    ones = {"11": 80, "01": 20}  # qubit 1 reads 0 in 20% of the shots that prepared 1
    measured = measured_assignment(zeros, ones, 2)
    # [qubit, (read 0 after 1, read 1 after 0)]
    assert np.allclose(measured, [[0.0, 0.1], [0.2, 0.0]])


def test_usable_drops_missing_and_broken_readings() -> None:
    newest = np.array([0.01, np.nan, 0.02, 0.5])
    old = np.array([0.02, 0.01, 0.9, 0.01])
    assert usable(newest, old).tolist() == [True, False, False, False]


def test_squared_contrast_is_the_change_squared_plus_a_cross_term() -> None:
    rng = np.random.default_rng(1)
    measured, newest, old = rng.uniform(0, 0.1, size=(3, 40))
    d, e = newest - old, measured - newest
    assert np.allclose(contrast(measured, newest, old), d**2 + 2 * d * e)


@pytest.mark.parametrize("loss", ["squared", "absolute"])
def test_share_is_one_at_the_newest_reading_and_minus_one_at_the_old(loss: str) -> None:
    rng = np.random.default_rng(2)
    newest, old = rng.uniform(0, 0.1, size=(2, 6, 10, 2))
    change = reading_change(newest, old, loss).sum()
    assert contrast(newest, newest, old, loss).sum() == pytest.approx(change)
    assert contrast(old, newest, old, loss).sum() == pytest.approx(-change)


def test_a_constant_offset_hides_the_change_from_the_absolute_loss_only() -> None:
    # Four runs on one qubit and direction. The newest reading is the device up to an offset
    # of 0.02, and the old reading lies 0.005 above or below the newest equally often.
    newest = np.full((4, 1, 1), 0.010)
    old = newest + np.array([0.005, -0.005, 0.005, -0.005]).reshape(4, 1, 1)
    measured = newest + 0.02
    mask = usable(newest, old)

    squared = contrast(measured, newest, old, "squared").sum() / reading_change(newest, old, "squared").sum()
    absolute = (
        contrast(measured, newest, old, "absolute").sum() / reading_change(newest, old, "absolute").sum()
    )
    assert squared == pytest.approx(1.0)
    assert absolute == pytest.approx(0.0)

    offset = symmetric_offset(measured, newest, old, mask)
    assert offset == pytest.approx(0.02)
    corrected = contrast(measured - offset, newest, old, "absolute").sum()
    assert corrected / reading_change(newest, old, "absolute").sum() == pytest.approx(1.0)


def test_symmetric_offset_ignores_masked_runs_and_is_zero_without_any() -> None:
    newest = np.array([[[0.01, 0.01]], [[0.01, 0.01]], [[0.01, 0.9]]])
    old = np.full((3, 1, 2), 0.01)
    measured = newest + np.array([0.004, 0.006, 0.3]).reshape(3, 1, 1)
    mask = usable(newest, old)
    mask[:, 0, 1] = False
    offset = symmetric_offset(measured, newest, old, mask)
    assert offset[0, 0] == pytest.approx(0.006)  # the median of 0.004, 0.006 and 0.3
    assert offset[0, 1] == 0.0


def test_sums_by_day_keep_runs_of_a_day_together() -> None:
    values = np.arange(12, dtype=float).reshape(4, 3)
    mask = np.ones((4, 3), dtype=bool)
    mask[1, 0] = False
    day = np.array([0, 0, 2, 2])
    # Day 0: 0+1+2 and 4+5; day 1: no run; day 2: 6+7+8 and 9+10+11.
    assert sums_by_day(values, mask, day, 3).tolist() == [12.0, 0.0, 51.0]


@pytest.mark.parametrize("statistic", ["pooled", "typical"])
def test_confirmed_share_and_its_interval(statistic: str) -> None:
    change = np.array([1.0, 2.0, 1.5, 0.5, 1.0, 2.0, 1.0, 1.0])
    same = confirmed_share(0.6 * change, change, statistic=statistic, resamples=500, seed=4)
    # Every day confirms the same share, so every resample does too.
    assert (same.estimate, same.low, same.high) == pytest.approx((0.6, 0.6, 0.6))
    assert same.days == 8

    contrasts = change * np.random.default_rng(5).normal(0.6, 0.3, size=8)
    noisy = confirmed_share(contrasts, change, statistic=statistic, resamples=2000, seed=4)
    assert noisy.low < noisy.estimate < noisy.high
    # The interval depends on the seed, not on the moment it is computed.
    assert noisy == confirmed_share(contrasts, change, statistic=statistic, resamples=2000, seed=4)

    with pytest.raises(ValueError, match="never changed"):
        confirmed_share(np.zeros(3), np.zeros(3), statistic=statistic)


def test_one_day_decides_the_pooled_share_and_not_the_typical_one() -> None:
    # Nine days confirm nothing; on the tenth the readings jump and the device follows.
    change = np.array([1.0] * 9 + [100.0])
    contrasts = np.array([0.0] * 9 + [100.0])
    assert confirmed_share(contrasts, change, statistic="pooled", resamples=200).estimate == pytest.approx(
        100 / 109
    )
    assert confirmed_share(contrasts, change, statistic="typical", resamples=200).estimate == 0.0
    # A day on which nothing changed has no ratio and is left out.
    padded = confirmed_share(
        np.append(contrasts, 0.0), np.append(change, 0.0), statistic="typical", resamples=200
    )
    assert padded.days == 10
    with pytest.raises(ValueError, match="statistic must be"):
        confirmed_share(contrasts, change, statistic="mean")


def test_the_three_verdicts() -> None:
    assert verdict(Share(0.6, 0.2, 0.9, 20), margin=0.25) == VERDICTS[0]
    assert verdict(Share(0.1, 0.05, 0.2, 20), margin=0.25) == VERDICTS[0]  # small, and still above 0
    assert verdict(Share(0.05, -0.1, 0.2, 20), margin=0.25) == VERDICTS[1]
    assert verdict(Share(0.2, -0.1, 0.6, 20), margin=0.25) == VERDICTS[2]
