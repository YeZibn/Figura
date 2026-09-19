"""CLI for an explicit, Gateway-backed real chart chain diagnostic."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ..client import load_environment
from .gateway import DEFAULT_GATEWAY_URL, DiagnosticGatewayError, GatewayDiagnosticClient
from .manifest import DiagnosticManifestError, load_manifest
from .report import build_report, write_report
from ..storage import StorageRootConflict, resolve_storage_paths


def main(argv: list[str] | None = None) -> int:
    load_environment()
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
        default=os.environ.get("CHARTAGENT_GATEWAY_URL", DEFAULT_GATEWAY_URL),
        help="Gateway API 根地址",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="诊断输出目录；默认使用 canonical data root 下的 diagnostics/",
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="确认执行真实 provider 调用；缺少该标志时只校验清单",
    )
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest, asset_root=args.asset_root)
    except DiagnosticManifestError as exc:
        print(json.dumps({"status": "invalid_manifest", "error": str(exc)}, ensure_ascii=False))
        return 2

    selected = manifest.samples
    if args.case_id:
        requested = set(args.case_id)
        unknown = requested - {sample.case_id for sample in manifest.samples}
        if unknown:
            print(json.dumps({"status": "invalid_case_id", "case_ids": sorted(unknown)}, ensure_ascii=False))
            return 2
        selected = tuple(sample for sample in manifest.samples if sample.case_id in requested)

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

    try:
        output_dir = resolve_storage_paths(diagnostics_root=args.output_dir).diagnostics
    except StorageRootConflict as exc:
        print(json.dumps({"status": "storage_conflict", "error": str(exc)}, ensure_ascii=False))
        return 2

    client = GatewayDiagnosticClient(
        args.base_url,
        poll_interval=args.poll_interval,
    )
    output: list[dict[str, object]] = []
    for sample in selected:
        try:
            run = client.run_sample(
                sample,
                provider=args.provider,
                timeout=args.timeout,
            )
            report = build_report(
                run.history,
                sample,
                requested_provider=args.provider,
                timed_out=run.timed_out,
            )
            json_path, markdown_path = write_report(report, output_dir)
            output.append(
                {
                    "case_id": sample.case_id,
                    "status": "diagnosed",
                    "run_id": run.run_id,
                    "run_status": run.status,
                    "json": str(Path(json_path).as_posix()),
                    "markdown": str(Path(markdown_path).as_posix()),
                    "first_failure": report.to_dict()["timeline"].get("first_failure"),
                }
            )
        except DiagnosticGatewayError as exc:
            output.append(
                {
                    "case_id": sample.case_id,
                    "status": "gateway_error",
                    "code": exc.code,
                    "error": exc.message,
                }
            )
    print(json.dumps({"status": "completed", "results": output}, ensure_ascii=False, indent=2))
    return 0 if all(item.get("status") == "diagnosed" for item in output) else 1


if __name__ == "__main__":
    raise SystemExit(main())
