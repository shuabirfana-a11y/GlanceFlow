import csv
import json
import runpy
from pathlib import Path

from glanceflow.evaluation.charts import generate_figures
from glanceflow.evaluation.dataset import load_manifest
from glanceflow.evaluation.runners import ABLATIONS
from glanceflow.safety.rules import ALL_RULES


OUTPUT=Path("outputs/evaluation")


def test_dataset_manifest_has_at_least_40_complete_real_files():
    manifest=load_manifest()
    assert manifest.sample_count >= 40
    assert len(manifest.samples) == manifest.sample_count
    assert all(sample.synthetic for sample in manifest.samples)
    assert all(Path(sample.input_path).is_file() for sample in manifest.samples)
    assert all(sample.scenario_tags and sample.annotation_notes for sample in manifest.samples)
    assert manifest.contains_team_capture is False
    for sample in manifest.samples:
        individual=json.loads(Path(f"evaluation/dataset/annotations/{sample.sample_id}.json").read_text(encoding="utf-8"))
        individual["input_path"] = str(Path(individual["input_path"]))
        assert individual == sample.model_dump(mode="json")


def test_all_three_systems_use_exactly_same_sample_ids():
    manifest=load_manifest(); expected={sample.sample_id for sample in manifest.samples}
    full=json.loads((OUTPUT/"full_system_results.json").read_text(encoding="utf-8"))
    baseline=json.loads((OUTPUT/"baseline_results.json").read_text(encoding="utf-8"))
    assert {item["sample_id"] for item in full["results"]} == expected
    for results in baseline["systems"].values():
        assert {item["sample_id"] for item in results} == expected
    ablations=json.loads((OUTPUT/"ablation_results.json").read_text(encoding="utf-8"))
    for config in ABLATIONS:
        assert {item["sample_id"] for item in ablations["results"] if item["system_id"] == config.ablation_id} == expected


def test_seven_ablation_configs_are_adapter_only_and_core_rules_remain():
    assert len(ABLATIONS) == 7
    assert len({config.ablation_id for config in ABLATIONS}) == 7
    assert len(ALL_RULES) == 15
    config=json.loads(Path("evaluation/experiments/ablation_config.json").read_text(encoding="utf-8"))
    assert config["adapter_only"] is True
    assert config["production_core_modified"] is False


def test_each_ablation_has_observable_effect_on_real_results():
    with (OUTPUT/"metrics_summary.csv").open(encoding="utf-8-sig",newline="") as handle:
        rows={row["system_id"]:row for row in csv.DictReader(handle)}
    full_errors=int(rows["full_system"]["erroneous_execution_numerator"])
    for config in ABLATIONS:
        assert int(rows[config.ablation_id]["erroneous_execution_numerator"]) > full_errors


def test_csv_and_json_outputs_are_parseable():
    for name in ("full_system_results.json","baseline_results.json","ablation_results.json","failure_cases.json","final_scorecard.json","metric_audit.json"):
        assert json.loads((OUTPUT/name).read_text(encoding="utf-8"))
    for name in ("metrics_summary.csv","latency_summary.csv","confusion_matrix.csv","metric_audit.csv"):
        with (OUTPUT/name).open(encoding="utf-8-sig",newline="") as handle:
            assert list(csv.DictReader(handle))
    assert (OUTPUT/"metric_audit.md").read_text(encoding="utf-8").startswith("# GlanceFlow")


def test_failure_cases_trace_to_real_run_results():
    failures=json.loads((OUTPUT/"failure_cases.json").read_text(encoding="utf-8"))
    full=json.loads((OUTPUT/"full_system_results.json").read_text(encoding="utf-8"))
    sample_ids={item["sample_id"] for item in full["results"]}
    assert failures["case_count"] >= 10
    assert all(case["sample_id"] in sample_ids for case in failures["cases"])
    assert all(case["trace_source"] == "由本次统一评测入口真实运行产生。" for case in failures["cases"])


def test_user_study_pending_has_no_fabricated_results():
    status=json.loads(Path("evaluation/reports/user-study-status.json").read_text(encoding="utf-8"))
    assert status == {
        "status":"PENDING_NOT_RECRUITED","participants_recruited":0,"sessions_completed":0,
        "results_available":False,"reason":"尚未实际招募团队内参与者；不得生成假结果。",
    }


def test_final_scorecard_references_full_system_metrics():
    score=json.loads((OUTPUT/"final_scorecard.json").read_text(encoding="utf-8"))
    with (OUTPUT/"metrics_summary.csv").open(encoding="utf-8-sig",newline="") as handle:
        full=next(row for row in csv.DictReader(handle) if row["system_id"] == "full_system")
    assert score["sample_count"] == load_manifest().sample_count
    assert score["erroneous_execution_rate"]["value"] == float(full["erroneous_execution_rate"])
    assert score["valid_coverage_rate"]["value"] == float(full["valid_coverage_rate"])
    reliability=json.loads((OUTPUT/"full_system_results.json").read_text(encoding="utf-8"))["reliability"]
    assert score["rollback_success_rate"] == reliability["rollback_success_rate"]
    assert score["real_glasses"] is False
    assert score["image_median_end_to_end_latency_ms"] > 0
    assert score["video_median_end_to_end_latency_ms"] > 0


def test_chart_generator_creates_all_seven_files(tmp_path):
    rate=lambda value:{"value":value,"numerator":1,"denominator":2,"display":f"{value*100:.2f}%"}
    metric=lambda name:{"system_id":name,"erroneous_execution_rate":rate(.2),"valid_coverage_rate":rate(.7),"false_rejection_rate":rate(.3),"package_complete_accuracy":rate(.7)}
    systems=[metric("A"),metric("B"),metric("full_system")]
    ablations=[metric(config.ablation_id) for config in ABLATIONS]
    statuses=["READY_TO_CONFIRM","NEED_USER_INPUT","CONTRADICTION_BLOCKED","RECAPTURE_REQUIRED"]
    confusion={actual:{predicted:int(actual==predicted) for predicted in statuses} for actual in statuses}
    latency=[]
    for input_type, stages in {
        "IMAGE":("ocr_ms","extraction_ms","safety_gate_ms","calendar_transaction_ms","total_ms"),
        "VIDEO":("frame_capture_ms","frame_selection_ms","ocr_ms","extraction_ms","safety_gate_ms","calendar_transaction_ms","total_ms"),
    }.items():
        latency.extend({"system_id":"full_system","input_type":input_type,"stage":stage,"effective_sample_count":2,"median_ms":1,"p90_ms":2} for stage in stages)
    reliability={key:rate(1) for key in ("readback_consistency_rate","rollback_success_rate","undo_success_rate")}
    paths=generate_figures(tmp_path,systems,ablations,confusion,latency,[{"error_layer":"quality"}],reliability,46)
    assert len(paths) == 7
    assert all(path.is_file() and path.stat().st_size > 0 for path in paths)


def test_user_study_and_real_data_materials_do_not_fabricate_results():
    study=Path("evaluation/user_study")
    expected={"recruitment_notice.md","consent_form.md","test_protocol.md","questionnaire.md","record_template.csv","analysis_script.py","README.md"}
    assert expected <= {path.name for path in study.iterdir()}
    namespace=runpy.run_path(study/"analysis_script.py")
    analysis=namespace["analyze"](study/"record_template.csv")
    assert analysis["status"] == "尚未执行"
    assert analysis["participants"] == 0 and analysis["results_available"] is False
    real_data=Path("evaluation/real_data")
    assert {"collection_protocol.md","privacy_checklist.md","annotation_template.json","manifest_template.csv"} <= {path.name for path in real_data.iterdir()}
    annotation=json.loads((real_data/"annotation_template.json").read_text(encoding="utf-8"))
    assert annotation["privacy_review"]["approved"] is False
