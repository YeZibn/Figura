"""CLI for Gateway-backed real chart diagnostics and evaluation bundles."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ..client import load_environment
from ..storage import StorageRootConflict, resolve_storage_paths
from .bundle import EvaluationBundle, EvaluationBundleError
from .gateway import DEFAULT_GATEWAY_URL, DiagnosticGatewayError, GatewayDiagnosticClient
from .gateway_process import ManagedGateway, ManagedGatewayError
from .manifest import DiagnosticManifest, DiagnosticManifestError, DiagnosticSample, load_manifest
from .report import build_report, write_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m chartagent.evaluation")
    parser.add_argument("--manifest", required=True, help="真实样本清单 JSON")
    parser.add_argument("--asset-root", default=None, help="样本相对路径根目录，默认寻找项目根目录")
    parser.add_argument("--case-id", action="append", help="只运行指定样本，可重复传入")
    parser.add_argument(
        "--provider",
        default=os.environ.get("CHARTAGENT_EVAL_PROVIDER"),
        help="显式 provider；也可使用 CHARTAGENT_EVAL_PROVIDER",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="显式使用外部 Gateway；不传时 --execute 默认托管评测专用 Gateway",
    )
    parser.add_argument(
        "--external-gateway",
        action="store_true",
        help="使用外部 Gateway 的兼容模式；结果只写入 diagnostics，不创建完整评测包",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="canonical data root；托管评测包默认创建在该目录的 evaluations/ 下",
    )
    parser.add_argument(
        "--evaluation-root",
        default=None,
        help="显式指定本次评测包根目录；目录必须尚不存在",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="外部 Gateway 兼容模式下的诊断输出目录",
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--gateway-startup-timeout", type=float, default=30.0)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="确认执行真实 provider 调用；缺少该标志时只校验清单",
    )
    return parser


def _select_samples(manifest: DiagnosticManifest, case_ids: list[str] | None) -> tuple[DiagnosticSample, ...]:
    if not case_ids:
        return manifest.samples
    requested = set(case_ids)
    unknown = requested - {sample.case_id for sample in manifest.samples}
    if unknown:
        raise DiagnosticManifestError(f"未知的 case_id: {', '.join(sorted(unknown))}")
    return tuple(sample for sample in manifest.samples if sample.case_id in requested)


def _client(base_url: str, args: argparse.Namespace) -> GatewayDiagnosticClient:
    return GatewayDiagnosticClient(
        base_url,
        timeout=min(30.0, max(0.1, float(args.timeout))),
        poll_interval=args.poll_interval,
    )


def _diagnosed_result(
    sample: DiagnosticSample,
    run: object,
    json_path: Path,
    markdown_path: Path,
    report: object,
) -> dict[str, object]:
    report_data = report.to_dict()  # type: ignore[attr-defined]
    timeline = report_data.get("timeline", {}) if isinstance(report_data, dict) else {}
    first_failure = timeline.get("first_failure") if isinstance(timeline, dict) else None
    return {
        "case_id": sample.case_id,
        "status": "diagnosed",
        "run_id": getattr(run, "run_id", None),
        "run_status": getattr(run, "status", "unknown"),
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
        "first_failure": first_failure,
    }


def _run_external(
    *,
    selected: tuple[DiagnosticSample, ...],
    args: argparse.Namespace,
    base_url: str,
) -> int:
    """Keep the pre-bundle workflow for an explicitly managed Gateway."""

    try:
        output_dir = resolve_storage_paths(
            data_dir=args.data_dir,
            diagnostics_root=args.output_dir,
        ).diagnostics
    except StorageRootConflict as exc:
        print(json.dumps({"status": "storage_conflict", "error": str(exc)}, ensure_ascii=False))
        return 2

    client = _client(base_url, args)
    output: list[dict[str, object]] = []
    for sample in selected:
        try:
            run = client.run_sample(
                sample,
                provider=args.provider,
                session_name=f"diagnostic-{sample.case_id}",
                timeout=args.timeout,
            )
            report = build_report(
                run.history,
                sample,
                requested_provider=args.provider,
                timed_out=run.timed_out,
            )
            json_path, markdown_path = write_report(report, output_dir)
            output.append(_diagnosed_result(sample, run, json_path, markdown_path, report))
        except DiagnosticGatewayError as exc:
            output.append(
                {
                    "case_id": sample.case_id,
                    "status": "gateway_error",
                    "code": exc.code,
                    "error": exc.message,
                }
            )
    print(json.dumps({"status": "completed", "mode": "external_gateway", "results": output}, ensure_ascii=False, indent=2))
    return 0 if all(item.get("status") == "diagnosed" for item in output) else 1


def _run_managed(
    *,
    manifest: DiagnosticManifest,
    selected: tuple[DiagnosticSample, ...],
    args: argparse.Namespace,
) -> int:
    try:
        bundle = EvaluationBundle.create(
            manifest=manifest,
            samples=selected,
            provider=args.provider,
            data_dir=args.data_dir,
            evaluation_root=args.evaluation_root,
        )
    except (EvaluationBundleError, StorageRootConflict) as exc:
        print(json.dumps({"status": "blocked", "code": "bundle_creation_failed", "error": str(exc)}, ensure_ascii=False))
        return 2

    gateway = ManagedGateway(
        bundle.root,
        startup_timeout=args.gateway_startup_timeout,
    )
    output: list[dict[str, object]] = []
    current: DiagnosticSample | None = None
    gateway_started = False
    batch_status = "partial"
    try:
        base_url = gateway.start()
        gateway_started = True
        client = _client(base_url, args)
        for sample in selected:
            current = sample
            bundle.start_case(sample)
            try:
                run = client.run_sample(
                    sample,
                    provider=args.provider,
                    session_name=f"eval-{bundle.evaluation_id}-{sample.case_id}"[:128],
                    timeout=args.timeout,
                )
                report = build_report(
                    run.history,
                    sample,
                    requested_provider=args.provider,
                    timed_out=run.timed_out,
                )
                json_path, markdown_path = write_report(report, bundle.diagnostics_dir)
                report_data = report.to_dict()
                bundle.finish_case(
                    sample,
                    run=run,
                    report=report_data,
                    report_paths=(json_path, markdown_path),
                )
                output.append(_diagnosed_result(sample, run, json_path, markdown_path, report))
            except DiagnosticGatewayError as exc:
                bundle.record_case_error(
                    sample,
                    code=exc.code,
                    message=exc.message,
                    status="blocked",
                    session_id=exc.session_id,
                    run_id=exc.run_id,
                )
                output.append(
                    {
                        "case_id": sample.case_id,
                        "status": "gateway_error",
                        "code": exc.code,
                        "error": exc.message,
                    }
                )
            current = None
        batch_status = bundle.finalize()
    except KeyboardInterrupt:
        if current is not None:
            bundle.record_case_error(
                current,
                code="user_cancelled",
                message="用户中断评测",
                status="interrupted",
            )
        batch_status = bundle.finalize(status="partial", error="用户中断评测")
        return_code = 130
    except ManagedGatewayError as exc:
        if current is not None:
            bundle.record_case_error(
                current,
                code=exc.code,
                message=exc.message,
                status="failed" if gateway_started else "blocked",
            )
        batch_status = bundle.finalize(
            status="partial" if gateway_started else "blocked",
            error=exc.message,
        )
        output.append({"status": "gateway_lifecycle_error", "code": exc.code, "error": exc.message})
        return_code = 1
    except Exception as exc:  # noqa: BLE001 - preserve a diagnostic bundle on unexpected failures
        if current is not None:
            bundle.record_case_error(
                current,
                code="evaluation_error",
                message=f"{type(exc).__name__}: evaluation failed",
                status="failed",
            )
        batch_status = bundle.finalize(status="partial", error="评测执行异常")
        output.append({"status": "evaluation_error", "error": type(exc).__name__})
        return_code = 1
    else:
        return_code = 0 if batch_status == "completed" else 1
    finally:
        gateway.close()

    print(
        json.dumps(
            {
                "status": batch_status,
                "mode": "managed_gateway",
                "evaluation_id": bundle.evaluation_id,
                "evaluation_root": str(bundle.root),
                "summary": "summary.json",
                "results": output,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return return_code


def main(argv: list[str] | None = None) -> int:
    load_environment()
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest, asset_root=args.asset_root)
        selected = _select_samples(manifest, args.case_id)
    except DiagnosticManifestError as exc:
        print(json.dumps({"status": "invalid_manifest", "error": str(exc)}, ensure_ascii=False))
        return 2

    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "manifest_valid",
                    "samples": [sample.case_id for sample in selected],
                    "next": "添加 --execute 并显式指定 --provider 后才会提交 Gateway run",
                },
                ensure_ascii=False,
            )
        )
        return 0
    if not isinstance(args.provider, str) or not args.provider.strip():
        print(json.dumps({"status": "provider_required", "error": "真实运行必须显式指定 --provider"}, ensure_ascii=False))
        return 2

    configured_base_url = args.base_url or os.environ.get("CHARTAGENT_GATEWAY_URL")
    external = bool(configured_base_url or args.external_gateway)
    if external:
        if args.evaluation_root:
            print(json.dumps({"status": "invalid_options", "error": "外部 Gateway 模式不能使用 --evaluation-root"}, ensure_ascii=False))
            return 2
        return _run_external(
            selected=selected,
            args=args,
            base_url=configured_base_url or DEFAULT_GATEWAY_URL,
        )
    if args.output_dir:
        print(json.dumps({"status": "invalid_options", "error": "托管评测请使用 --evaluation-root；--output-dir 仅适用于外部 Gateway"}, ensure_ascii=False))
        return 2
    return _run_managed(manifest=manifest, selected=selected, args=args)


if __name__ == "__main__":
    raise SystemExit(main())
