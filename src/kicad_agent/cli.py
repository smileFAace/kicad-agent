"""CLI wrapper for kicad-agent -- run operations from the terminal.

Usage examples::

    # Print the operation JSON Schema
    kicad-agent --schema

    # Run an operation from inline JSON
    kicad-agent '{"op_type": "add_component", ...}'

    # Run an operation from a file
    kicad-agent operation.json

    # Validate without executing
    kicad-agent --dry-run operation.json

    # Specify project directory
    kicad-agent -p /path/to/project operation.json

    # Collect training data from GitHub
    kicad-agent collect --max-repos 100
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from kicad_agent.handler import format_result, handle_operation, validate_operation
from kicad_agent.ops.schema import get_operation_schema

_SUBCOMMANDS = {"collect", "erc", "drc", "export", "context", "route", "analyze", "component-search", "ai-stats"}


def _build_operation_parser() -> argparse.ArgumentParser:
    """Parser for the legacy operation mode."""
    parser = argparse.ArgumentParser(
        prog="kicad-agent",
        description="Run kicad-agent operations from the terminal.",
    )

    parser.add_argument(
        "operation",
        nargs="?",
        default=None,
        help=(
            "JSON string or path to a JSON file containing the operation. "
            "If the argument starts with '{', it is treated as inline JSON; "
            "otherwise, it is treated as a file path."
        ),
    )

    parser.add_argument(
        "--project-dir",
        "-p",
        type=Path,
        default=None,
        help="Project directory (defaults to current working directory).",
    )

    parser.add_argument(
        "--schema",
        "-s",
        action="store_true",
        help="Print the operation JSON Schema and exit.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the operation without executing.",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed output including operation details dict.",
    )

    return parser


def _build_collect_parser() -> argparse.ArgumentParser:
    """Parser for the 'collect' subcommand."""
    parser = argparse.ArgumentParser(
        prog="kicad-agent collect",
        description="Collect real-world KiCad training data from GitHub.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN"),
        help="GitHub PAT with public_repo scope (default: GITHUB_TOKEN env var).",
    )
    parser.add_argument(
        "--max-repos",
        type=int,
        default=500,
        help="Maximum repos to discover (default: 500).",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=Path("kicad_staging"),
        help="Local dir for downloaded files (default: kicad_staging).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training_output/real_boards"),
        help="Output dir for train/val/test JSONL (default: training_output/real_boards).",
    )
    return parser


def _read_operation(raw: str) -> str:
    """Read operation JSON from inline string or file path.

    Args:
        raw: Either an inline JSON string (starts with ``{``) or a file path.

    Returns:
        The JSON string to validate.

    Raises:
        SystemExit: If the file cannot be read.
    """
    if raw.startswith("{"):
        return raw

    path = Path(raw)
    if not path.exists():
        print(f"Error: file not found: {raw}", file=sys.stderr)
        sys.exit(1)

    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error reading file: {exc}", file=sys.stderr)
        sys.exit(1)


def _handle_collect(argv: list[str]) -> None:
    """Handle the 'collect' subcommand."""
    parser = _build_collect_parser()
    args = parser.parse_args(argv)

    if not args.token:
        print("Error: --token or GITHUB_TOKEN env var required", file=sys.stderr)
        sys.exit(1)

    from kicad_agent.training.real_dataset import run_pipeline

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    args.staging_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    dataset = run_pipeline(
        token=args.token,
        staging_dir=args.staging_dir,
        max_repos=args.max_repos,
        output_dir=args.output_dir,
    )

    meta = dataset.metadata
    print(f"\nCollection complete: {len(dataset)} samples")
    print(f"  Discovered:    {meta.get('n_discovered', 0)} file pairs")
    print(f"  Parsed:        {meta.get('n_parsed', 0)} boards")
    print(f"  Duplicates:    {meta.get('n_duplicates_removed', 0)} removed")
    print(f"  Low quality:   {meta.get('n_quality_removed', 0)} removed")
    print(f"  Difficulty:    {dict(dataset.difficulty_counts)}")
    print(f"  Output:        {args.output_dir}/")

    sys.exit(0)


def _run_kicad_cli(args: list[str], capture: bool = False) -> subprocess.CompletedProcess | None:
    """Run kicad-cli if available, print friendly error if not.

    Args:
        args: Arguments to pass to kicad-cli.
        capture: If True, return the CompletedProcess instead of printing.

    Returns:
        CompletedProcess if capture=True, None otherwise.
    """
    try:
        result = subprocess.run(
            ["kicad-cli"] + args,
            capture_output=capture,
            text=True,
            timeout=120,
        )
        if capture:
            return result
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
        return None
    except FileNotFoundError:
        print("Error: kicad-cli not found. Install KiCad 8+ and ensure kicad-cli is on PATH.", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("Error: kicad-cli timed out after 120s.", file=sys.stderr)
        sys.exit(1)


def _handle_erc(argv: list[str]) -> None:
    """Handle the 'erc' subcommand — run Electrical Rules Check on a schematic."""
    parser = argparse.ArgumentParser(
        prog="kicad-agent erc",
        description="Run ERC (Electrical Rules Check) on a KiCad schematic.",
    )
    parser.add_argument("schematic", type=Path, help="Path to .kicad_sch file")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output report file (default: stdout)")
    args = parser.parse_args(argv)

    if not args.schematic.exists():
        print(f"Error: schematic not found: {args.schematic}", file=sys.stderr)
        sys.exit(1)

    cmd = ["erc", str(args.schematic)]
    if args.output:
        cmd.extend(["-o", str(args.output)])

    _run_kicad_cli(cmd)
    sys.exit(0)


def _handle_drc(argv: list[str]) -> None:
    """Handle the 'drc' subcommand — run Design Rules Check on a PCB."""
    parser = argparse.ArgumentParser(
        prog="kicad-agent drc",
        description="Run DRC (Design Rules Check) on a KiCad PCB.",
    )
    parser.add_argument("pcb", type=Path, help="Path to .kicad_pcb file")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output report file (default: stdout)")
    args = parser.parse_args(argv)

    if not args.pcb.exists():
        print(f"Error: PCB file not found: {args.pcb}", file=sys.stderr)
        sys.exit(1)

    cmd = ["drc", str(args.pcb)]
    if args.output:
        cmd.extend(["-o", str(args.output)])

    _run_kicad_cli(cmd)
    sys.exit(0)


def _handle_export(argv: list[str]) -> None:
    """Handle the 'export' subcommand — export PCB to various formats."""
    parser = argparse.ArgumentParser(
        prog="kicad-agent export",
        description="Export a KiCad PCB to Gerber, BOM, position, or STEP format.",
    )
    parser.add_argument("format", choices=["gerber", "bom", "position", "step"],
                        help="Export format")
    parser.add_argument("pcb", type=Path, help="Path to .kicad_pcb file")
    parser.add_argument("-o", "--output-dir", type=Path, default=None,
                        help="Output directory (default: same as PCB file)")
    args = parser.parse_args(argv)

    if not args.pcb.exists():
        print(f"Error: PCB file not found: {args.pcb}", file=sys.stderr)
        sys.exit(1)

    output_dir = args.output_dir or args.pcb.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    format_cmds = {
        "gerber": ["pcb", "export", "gerbers", "-o", str(output_dir), str(args.pcb)],
        "bom": ["pcb", "export", "bom", "-o", str(output_dir / "bom.csv"), str(args.pcb)],
        "position": ["pcb", "export", "pos", "--format", "csv", "-o", str(output_dir / "position.csv"), str(args.pcb)],
        "step": ["pcb", "export", "step", "-o", str(output_dir / (args.pcb.stem + ".step")), str(args.pcb)],
    }

    _run_kicad_cli(format_cmds[args.format])
    sys.exit(0)


def _handle_context(argv: list[str]) -> None:
    """Handle the 'context' subcommand — show project summary."""
    parser = argparse.ArgumentParser(
        prog="kicad-agent context",
        description="Show a summary of a KiCad project.",
    )
    parser.add_argument("project_dir", type=Path, nargs="?", default=Path("."),
                        help="Path to KiCad project directory (default: current dir)")
    args = parser.parse_args(argv)

    if not args.project_dir.exists():
        print(f"Error: directory not found: {args.project_dir}", file=sys.stderr)
        sys.exit(1)

    # Find project files
    pro_files = list(args.project_dir.glob("*.kicad_pro"))
    sch_files = list(args.project_dir.glob("*.kicad_sch"))
    pcb_files = list(args.project_dir.glob("*.kicad_pcb"))

    if not pro_files and not sch_files and not pcb_files:
        print(f"No KiCad files found in {args.project_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Project: {args.project_dir.resolve().name}")
    print(f"  Project files: {len(pro_files)}")
    print(f"  Schematics:    {len(sch_files)}")
    print(f"  PCBs:          {len(pcb_files)}")

    # Parse first schematic for component summary
    if sch_files:
        try:
            from kicad_agent.parser import parse_schematic
            from kicad_agent.ir.schematic_ir import SchematicIR

            result = parse_schematic(sch_files[0])
            ir = SchematicIR(_parse_result=result)
            components = ir.components
            print(f"\n  Schematic: {sch_files[0].name}")
            print(f"    Components: {len(components)}")

            # Count by prefix
            prefix_counts: dict[str, int] = {}
            for comp in components:
                ref = getattr(comp, 'reference', '') or ''
                prefix = ''.join(c for c in ref if c.isalpha())
                prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
            for prefix, count in sorted(prefix_counts.items()):
                print(f"      {prefix or '(unref)'}: {count}")
        except (ValueError, FileNotFoundError, OSError, RuntimeError) as exc:
            print(f"    (Could not parse schematic: {exc})")

    # Parse first PCB for board summary
    if pcb_files:
        try:
            from kicad_agent.parser import parse_pcb
            from kicad_agent.parser.uuid_extractor import extract_uuids
            from kicad_agent.ir.pcb_ir import PcbIR

            result = parse_pcb(pcb_files[0])
            uuid_map = extract_uuids(result.raw_content, "pcb")
            ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

            fps = ir.footprints
            nets = ir.nets
            bounds = ir.get_board_bounds()
            print(f"\n  PCB: {pcb_files[0].name}")
            print(f"    Footprints: {len(fps)}")
            print(f"    Nets: {len(nets)}")
            if bounds:
                w = bounds[2] - bounds[0]
                h = bounds[3] - bounds[1]
                print(f"    Board size: {w:.1f} x {h:.1f} mm")
        except (ValueError, FileNotFoundError, OSError, RuntimeError) as exc:
            print(f"    (Could not parse PCB: {exc})")

    sys.exit(0)


def _handle_route(argv: list[str]) -> None:
    """Handle the 'route' subcommand — auto-route nets on a PCB."""
    parser = argparse.ArgumentParser(
        prog="kicad-agent route",
        description="Auto-route nets on a KiCad PCB using A* pathfinding.",
    )
    parser.add_argument("pcb", type=Path, help="Path to .kicad_pcb file")
    parser.add_argument("--nets", nargs="*", default=[], help="Net names to route (default: all)")
    parser.add_argument("--layer", default="F.Cu", help="Target copper layer (default: F.Cu)")
    args = parser.parse_args(argv)

    if not args.pcb.exists():
        print(f"Error: PCB file not found: {args.pcb}", file=sys.stderr)
        sys.exit(1)

    # Build and execute auto_route operation
    op_json = json.dumps({
        "op_type": "auto_route",
        "target_file": str(args.pcb.resolve().relative_to(Path.cwd())),
        "nets": args.nets,
        "layer": args.layer,
    })

    from kicad_agent.handler import handle_operation, format_result
    result = handle_operation(op_json)

    if result.success:
        print(f"Routing complete: {result.details.get('routed_nets', 0)} nets, "
              f"{result.details.get('segments', 0)} segments")
        failed = result.details.get("failed_nets", [])
        if failed:
            print(f"  Failed nets: {', '.join(failed)}")
    else:
        print(format_result(result), file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


def _build_analyze_parser() -> argparse.ArgumentParser:
    """Parser for the 'analyze' subcommand -- local PCB reasoning."""
    parser = argparse.ArgumentParser(
        prog="kicad-agent analyze",
        description="Analyze a PCB or schematic using the fine-tuned local model.",
    )
    parser.add_argument(
        "file",
        type=Path,
        help="Path to .kicad_pcb or .kicad_sch file.",
    )
    parser.add_argument(
        "--adapter",
        type=Path,
        default=None,
        help="LoRA adapter directory (default: auto-detect GRPO > SFT).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Base model (default: Qwen/Qwen2.5-0.5B-Instruct).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1024,
        help="Max generation tokens (default: 1024).",
    )
    parser.add_argument(
        "--n-best",
        type=int,
        default=4,
        help="Number of chains for best-of-N selection (default: 4).",
    )
    parser.add_argument(
        "--reward-model",
        type=Path,
        default=None,
        help="Reward model directory (default: training_output/unified).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-chain scores and timing.",
    )
    return parser


def _handle_analyze(argv: list[str]) -> None:
    """Handle the 'analyze' subcommand using generate_analysis with best-of-N."""
    from kicad_agent.inference.wrapper import generate_analysis

    parser = _build_analyze_parser()
    args = parser.parse_args(argv)

    if not args.file.exists():
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    file_path = args.file

    # Extract board stats for display header
    try:
        from kicad_agent.inference.wrapper import InferenceWrapper
        stats = InferenceWrapper._extract_board_stats(file_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except (OSError, RuntimeError) as exc:
        print(f"Warning: Could not parse file ({exc}), using defaults.", file=sys.stderr)
        stats = None

    print(f"Analyzing {file_path.name}...")
    if stats:
        print(f"  Components: {stats.n_components}, Nets: {stats.n_nets}, Layers: {stats.n_layers}")
        if stats.width_mm > 0:
            print(f"  Board size: {stats.width_mm:.1f} x {stats.height_mm:.1f} mm")
    print(f"  Best-of-N: {args.n_best} chains generated")
    print()

    # Run inference via generate_analysis
    try:
        result = generate_analysis(
            file_path=str(file_path),
            model=args.model,
            adapter_dir=args.adapter,
            reward_model_dir=args.reward_model,
            n_best=args.n_best,
            max_tokens=args.max_tokens,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Print chain text
    print(result.chain_text)
    print()

    # Print scores
    print(
        f"Score: {result.composite_score:.3f} "
        f"(format={result.format_score:.2f}, "
        f"quality={result.quality_score:.2f}, "
        f"accuracy={result.accuracy_score:.2f})"
    )

    if args.verbose:
        print(f"  Generation time: {result.generation_time_s:.1f}s")


def _handle_component_search(argv: list[str]) -> None:
    """Handle the 'component-search' subcommand — start MCP server."""
    from kicad_agent.mcp.server import main as mcp_main
    mcp_main()


def _handle_ai_stats(argv: list[str]) -> None:
    """Handle the 'ai-stats' subcommand — show local-first AI intervention metrics."""
    parser = argparse.ArgumentParser(
        prog="kicad-agent ai-stats",
        description="Show local-first AI intervention metrics and training gaps.",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path(".kicad_agent_tracking"),
        help="Tracking data directory (default: .kicad_agent_tracking)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted report.",
    )
    args = parser.parse_args(argv)

    if not args.dir.exists():
        print(f"No tracking data found at {args.dir}", file=sys.stderr)
        print("Run some LLM operations with KICAD_AGENT_LLM_MODE=local_first first.", file=sys.stderr)
        sys.exit(1)

    from kicad_agent.ai_tracking.tracker import InterventionTracker
    from kicad_agent.ai_tracking.gap_analyzer import GapAnalyzer
    from kicad_agent.ai_tracking.stats import format_stats_report

    tracker = InterventionTracker(directory=args.dir)
    events = tracker.query()

    if not events:
        print("No intervention events recorded yet.", file=sys.stderr)
        sys.exit(0)

    analyzer = GapAnalyzer()
    report = analyzer.analyze(events)

    if args.json:
        import dataclasses
        print(json.dumps(dataclasses.asdict(report), indent=2, default=str))
    else:
        print(format_stats_report(report))


def main(argv: list[str] | None = None) -> None:
    """Entry point for the kicad-agent CLI."""
    if argv is None:
        argv = sys.argv[1:]

    # Route subcommands to their own parsers
    if argv and argv[0] in _SUBCOMMANDS:
        subcmd = argv[0]
        subcmd_argv = argv[1:]
        if subcmd == "collect":
            _handle_collect(subcmd_argv)
        elif subcmd == "erc":
            _handle_erc(subcmd_argv)
        elif subcmd == "drc":
            _handle_drc(subcmd_argv)
        elif subcmd == "export":
            _handle_export(subcmd_argv)
        elif subcmd == "context":
            _handle_context(subcmd_argv)
        elif subcmd == "route":
            _handle_route(subcmd_argv)
        elif subcmd == "analyze":
            _handle_analyze(subcmd_argv)
        elif subcmd == "component-search":
            _handle_component_search(subcmd_argv)
        elif subcmd == "ai-stats":
            _handle_ai_stats(subcmd_argv)
        return

    # Legacy operation mode
    parser = _build_operation_parser()
    args = parser.parse_args(argv)

    # --schema: print schema and exit
    if args.schema:
        schema = get_operation_schema()
        print(json.dumps(schema, indent=2))
        sys.exit(0)

    # Require an operation argument if not --schema
    if args.operation is None:
        parser.error("the following arguments are required: operation")

    # Read the operation JSON
    json_str = _read_operation(args.operation)

    # Resolve project directory
    project_dir = args.project_dir

    # --dry-run: validate only
    if args.dry_run:
        _op, err = validate_operation(json_str)
        if err is not None:
            print(format_result(err), file=sys.stderr)
            sys.exit(1)
        print("Validation passed.")
        sys.exit(0)

    # Execute the operation
    result = handle_operation(json_str, project_dir=project_dir)

    if args.verbose and hasattr(result, "details"):
        output = format_result(result)
        if result.details:
            output += "\n  Details:"
            for key, value in result.details.items():
                output += f"\n    {key}: {value}"
        print(output)
    else:
        print(format_result(result))

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
