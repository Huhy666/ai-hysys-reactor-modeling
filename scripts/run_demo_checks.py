"""Run on the HYSYS workstation, in the signed-in user's interactive session."""

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.domain.demo_specs import generalization_specs, reforming_spec, toluene_spec  # noqa: E402

PROMPTS = {
    "toluene": "模拟甲苯歧化，使用Peng-Robinson，纯甲苯10000 kg/h，进料380℃、"
               "2500 kPa绝压，总转化率50%，不研究动力学，不考虑副反应。"
               "2甲苯生成苯和二甲苯，包含邻、间、对三种异构体。"
               "请提出等选择性、绝热和零压降假设，等待用户确认。",
    "reforming": "使用Peng-Robinson和可用的热力学平衡数据模拟甲烷蒸汽重整。"
                 "进料甲烷1000 kmol/h、水2700 kmol/h，总流量3700 kmol/h，"
                 "进料520℃、1350 kPa绝压。CH4+H2O⇌CO+3H2，CO+H2O⇌CO2+H2。"
                 "比较出口温度600℃和710℃，出口绝对压力均为1350 kPa，压降均为0 kPa。",
}

PROMPTS.update({
    "shift": "使用Peng-Robinson模拟CO+H2O→CO2+H2，CO基准转化率30%，不研究动力学。"
             "Feed进料300 kmol/h，CO摩尔分数1/3、Water摩尔分数2/3，300℃、1000 kPa绝压。"
             "组分Carbon Monoxide、Water、Carbon Dioxide、Hydrogen。不预先指定反应器类型。",
    "reverse_shift": "使用Peng-Robinson模拟CO2+H2→CO+H2O，CO2基准转化率20%，不研究动力学。"
                     "Feed进料300 kmol/h，Carbon Dioxide摩尔分数1/3、Hydrogen摩尔分数2/3，"
                     "300℃、1000 kPa绝压。包含产物Carbon Monoxide、Water。不指定反应器类型。",
    "methanation": "使用Peng-Robinson模拟CO2+4H2→CH4+2H2O，CO2基准转化率10%，不研究动力学。"
                   "Feed进料300 kmol/h，Carbon Dioxide摩尔分数1/6、Hydrogen摩尔分数5/6，"
                   "300℃、1000 kPa绝压。包含产物Methane、Water。不指定反应器类型。",
})


def discover() -> list[str]:
    candidates = [PROJECT_ROOT / ".env", Path(r"C:\AI-HYSYS\.env")]
    root = Path(r"C:\AI-HYSYS")
    if root.is_dir():
        for directory, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in {".venv", "runs", ".git", "node_modules"}]
            if len(Path(directory).relative_to(root).parts) >= 3:
                dirs[:] = []
            if ".env" in files:
                candidates.append(Path(directory) / ".env")
    return list(dict.fromkeys(str(p.resolve()) for p in candidates if p.is_file()))


def main() -> int:
    print("Acceptance build: 2026-10-26-deadline-bridge", flush=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--scenario", choices=["toluene", "reforming", "all", "generalization"],
                        default="toluene")
    parser.add_argument("--require-ai", action="store_true")
    parser.add_argument("--require-hysys", action="store_true")
    parser.add_argument("--confirm-demo-assumptions", action="store_true",
                        help="Confirm equal xylene split, adiabatic/zero-drop conversion, "
                             "and reforming flow/equilibrium-data assumptions")
    args = parser.parse_args()
    os.chdir(PROJECT_ROOT)
    paths = discover()
    if args.discover:
        print(json.dumps({"configuration_candidates": paths}, ensure_ascii=False, indent=2))
        return 0
    env_file = args.env_file
    if env_file is None:
        usable = [path for path in paths if Settings(_env_file=path).hysys_base_case_path]
        if str(PROJECT_ROOT / ".env") in usable:
            usable = [str(PROJECT_ROOT / ".env")]
        if len(usable) > 1:
            print("Multiple configurations found. Select one with --env-file:")
            print("\n".join(usable))
            return 2
        env_file = Path(usable[0]) if usable else PROJECT_ROOT / ".env"
    settings = Settings(_env_file=env_file)
    output = settings.hysys_artifact_dir.resolve() / (
        "acceptance-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    output.mkdir(parents=True)
    report = {"mode": "natural_language" if args.require_ai else "structured_diagnostic",
              "created_at": datetime.now(UTC).isoformat(), "checks": [], "passed": False}

    def record(name, passed, detail=""):
        report["checks"].append({"name": name, "passed": passed, "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}", flush=True)
        (output / "acceptance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    if not args.confirm_demo_assumptions:
        record("assumptions", False, "Review docs/remote-acceptance.md, then explicitly "
               "add --confirm-demo-assumptions to authorize the documented assumptions.")
        return 2
    if not settings.hysys_base_case_path or not settings.hysys_base_case_path.is_file():
        record("base_case", False, "HYSYS_BASE_CASE_PATH must name an existing .hsc seed")
        return 2
    if args.require_ai and not settings.ai_is_configured:
        record("ai_configuration", False, "Configure LLM_BASE_URL, LLM_MODEL and LLM_API_KEY")
        return 2
    try:
        if args.require_hysys:
            from scripts.probe_hysys import run_probe
            probe_path = output / "probe-result.json"
            probe = run_probe(settings, probe_path)
            record("hysys_probe", probe.all_required, "See probe-result.json")
            if not probe.all_required:
                return 1
            settings.hysys_probe_result_path = probe_path
        from fastapi.testclient import TestClient

        from app.main import create_app
        examples = {
            "toluene": toluene_spec(confirmed=True), "reforming": reforming_spec(confirmed=True),
            **generalization_specs(confirmed=True),
        }
        if args.scenario == "generalization":
            scenarios = ["shift", "reverse_shift", "methanation"]
        else:
            scenarios = ["toluene", "reforming"] if args.scenario == "all" else [args.scenario]
        with TestClient(create_app(settings)) as client:
            for scenario in scenarios:
                spec = examples[scenario]
                if args.require_ai:
                    assumption_text = json.dumps(
                        [item.text for item in spec.assumptions], ensure_ascii=False,
                    )
                    text = PROMPTS[scenario] + (
                        " 仅将以下假设逐字写入assumptions，confirmed=false：" + assumption_text
                    )
                    parsed = client.post("/api/specs/parse", json={"text": text})
                    parsed.raise_for_status()
                    payload = parsed.json()
                    (output / f"{scenario}-parse.json").write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
                    )
                    if payload.get("issues") or not payload.get("spec"):
                        raise ValueError(f"{scenario}: natural-language parse blocked")
                    draft = payload["spec"]
                    # Confirm only the explicit scenario assumptions listed by the operator.
                    allowed = {item.text for item in spec.assumptions}
                    for assumption in draft.get("assumptions", []):
                        if assumption.get("text") not in allowed:
                            raise ValueError("AI proposed an additional assumption; review "
                                             f"{scenario}-parse.json in the Web UI")
                        assumption["confirmed"] = True
                    draft["assumptions"] = [item.model_dump() for item in spec.assumptions]
                    if scenario == "reforming":
                        draft["equilibrium_data_available"] = True
                    prepared = client.post("/api/specs/prepare", json=draft)
                    prepared.raise_for_status()
                    if not prepared.json()["executable"]:
                        raise ValueError(f"{scenario}: incomplete AI specification; "
                                         "review parse file and Web clarification")
                    spec = type(spec).model_validate(prepared.json()["spec"])
                response = client.post("/api/runs", json={"spec": spec.model_dump(mode="json"),
                    "original_text": text if args.require_ai else "structured diagnostic",
                    "auto_start": True})
                response.raise_for_status()
                run = response.json()
                if run["state"] != "queued":
                    raise ValueError(f"{scenario}: not queued: {run['decision']}")
                deadline = time.monotonic() + settings.hysys_run_timeout_seconds * 4 + 60
                last = None
                while time.monotonic() < deadline:
                    run = client.get(f"/api/runs/{run['id']}").json()
                    if run["state"] != last:
                        print(f"{scenario}: {run['id']} {run['state']}", flush=True)
                        last = run["state"]
                    if last in {"succeeded", "failed", "cancelled"}:
                        break
                    time.sleep(0.5)
                result = run.get("result") or {}
                success = (run["state"] == "succeeded" and result.get("source") == "hysys"
                           and result.get("converged") and bool(result.get("validation")))
                record(scenario, bool(success), f"run_id={run['id']}; {run.get('error') or ''}")
                if not success:
                    return 1
                if any("operator_attention_requested" in warning
                       for warning in result.get("warnings", [])):
                    report["interaction"] = "operator_attention_requested"
                    print("NOTE: operator attention requested; this run is not proof of "
                          "fully unattended automation.", flush=True)
                expected_cases = 2 if scenario == "reforming" else 1
                paths = result.get("case_paths", [])
                if len(paths) != expected_cases or not all(Path(p).is_file() for p in paths):
                    raise ValueError(f"{scenario}: missing HYSYS case artifacts")
                for filename in ["result.json", "streams.csv", *[Path(p).name for p in paths]]:
                    client.get(f"/api/runs/{run['id']}/artifacts/{filename}").raise_for_status()
                record(f"{scenario}_downloads", True, "JSON, CSV and HYSYS cases available")
        report["passed"] = all(item["passed"] for item in report["checks"])
        record("acceptance", report["passed"], report["mode"])
        return 0 if report["passed"] else 1
    except Exception as exc:
        # Provider errors are already sanitized by the API; never dump Settings or credentials.
        record("execution", False, f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        print(f"Report directory: {output}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
