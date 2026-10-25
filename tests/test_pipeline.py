"""Tests for the end-to-end pipeline script (D82, D83). Offline: no stage is run."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import compare_models  # noqa: E402
import run_pipeline  # noqa: E402


def test_default_arguments_run_every_stage_in_order():
    # With no arguments every stage is run, in pipeline order, without forcing the test.
    args = run_pipeline.parse_arguments([])
    assert run_pipeline.ordered_stages(args.stages) == list(run_pipeline.STAGES)
    assert args.force_test is False


def test_requested_stages_are_run_in_pipeline_order():
    # Stages given in any order are run in pipeline order.
    args = run_pipeline.parse_arguments(["--stages", "sensitivity", "data"])
    assert run_pipeline.ordered_stages(args.stages) == ["data", "sensitivity"]


def test_unknown_stage_is_refused():
    # An unknown stage name stops the program with a usage error.
    with pytest.raises(SystemExit):
        run_pipeline.parse_arguments(["--stages", "plot"])


def test_result_hashes_skip_logs_manifest_and_benchmarks(tmp_path, monkeypatch):
    # Only result files are hashed: logs, the manifest and timings are excluded.
    (tmp_path / "phase6_strategy.csv").write_text("a,b\n1,2\n")
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "phase6_curve.png").write_bytes(b"png")
    for name in ("pipeline_manifest.json", "pipeline.log", "test_runs.log", "phase8_knn.csv",
                 "test_report.html"):
        (tmp_path / name).write_text("changes every run")
    (tmp_path / "coverage").mkdir()
    (tmp_path / "coverage" / "index.html").write_text("coverage")
    monkeypatch.setattr(run_pipeline, "REPORTS", tmp_path)

    hashes = run_pipeline.result_hashes()

    assert sorted(hashes) == ["figures/phase6_curve.png", "phase6_strategy.csv"]
    assert hashes["phase6_strategy.csv"] == run_pipeline.sha256(tmp_path / "phase6_strategy.csv")


def test_changed_results_ignores_new_files_and_reports_changed_ones():
    # Only files whose hash changed are reported; new files are not "changed".
    previous = {"a.csv": "1", "b.csv": "2"}
    current = {"a.csv": "1", "b.csv": "3", "new.csv": "4"}
    assert run_pipeline.changed_results(previous, current) == ["b.csv"]
    assert run_pipeline.changed_results(previous, {"a.csv": "1", "b.csv": "2"}) == []


def test_selections_agree_compares_selected_model_and_family_winners():
    # Same shape as reports/model_selection.json ("selection" part).
    winners = {"polynomial": "polynomial degree 1", "wear_ode": "wear ODE", "knn": "knn k=100 uniform"}
    frozen = {"C3": {"selected": "polynomial degree 1", "family_winners": winners, "best_rmse": 0.63}}
    same = {"C3": {"selected": "polynomial degree 1", "family_winners": dict(winners), "best_rmse": 0.63}}
    other_model = {"C3": {"selected": "wear ODE", "family_winners": winners}}
    other_knn = {"C3": {"selected": "polynomial degree 1",
                        "family_winners": {**winners, "knn": "knn k=50 uniform"}}}
    unknown_compound = {"C4": same["C3"]}
    assert compare_models.selections_agree(frozen, same)
    assert not compare_models.selections_agree(frozen, other_model)
    assert not compare_models.selections_agree(frozen, other_knn)
    assert not compare_models.selections_agree(frozen, unknown_compound)


def test_hash_ignores_line_endings_of_text_files_only(tmp_path):
    # CRLF and LF text files hash the same; binary files keep their exact bytes.
    (tmp_path / "lf.csv").write_bytes(b"a,b\n1,2\n")
    (tmp_path / "crlf.csv").write_bytes(b"a,b\r\n1,2\r\n")
    (tmp_path / "lf.png").write_bytes(b"a\nb")
    (tmp_path / "crlf.png").write_bytes(b"a\r\nb")
    assert run_pipeline.sha256(tmp_path / "lf.csv") == run_pipeline.sha256(tmp_path / "crlf.csv")
    assert run_pipeline.sha256(tmp_path / "lf.png") != run_pipeline.sha256(tmp_path / "crlf.png")
