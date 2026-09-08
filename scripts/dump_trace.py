"""Print a capture as a source-aligned view: what each runtime source reported, per task execution.

    python scripts/dump_trace.py docs/traces/tau2_task39_qwen14b_clean.jsonl

`--out` writes it next to the trace as `<trace>.capture.txt`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from firebreak.tracing.recorder import Trace
from firebreak.tracing.view import render_trace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+")
    parser.add_argument("--out", action="store_true", help="write <trace>.capture.txt instead of printing")
    parser.add_argument("--no-checkpoints", action="store_true", help="omit the checkpointer ledger")
    args = parser.parse_args(argv)
    for raw in args.traces:
        path = Path(raw)
        text = render_trace(Trace.from_jsonl(str(path)), source_name=path.name,
                            show_checkpoints=not args.no_checkpoints)
        if args.out:
            target = Path(f"{path.with_suffix('')}.capture.txt")
            target.write_text(text)
            print(f"{path}  ->  {target.name}")
        else:
            print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
