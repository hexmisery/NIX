import argparse
import asyncio
import json
from pathlib import Path
import sys
import threading

from .catalog import Catalog
from .engine import scan
from .export import export_results
from .paths import assets, state_dir
from .updater import active_catalogs


def main():
    parser = argparse.ArgumentParser(prog="NIX")
    parser.add_argument("--cli", metavar="USERNAME")
    parser.add_argument("--full", action="store_true")
    parser.add_argument(
        "--region",
        choices=("all", "cis_scope", "asia_scope", "europe_scope", "americas_scope"),
        default="all",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        root = state_dir()
        if args.cli:
            catalog = Catalog(
                active_catalogs(root),
                root / "custom-sites.json",
                root / "discovered-forums.json",
            )
            sites = catalog.select(args.full, priority=args.region)
            if not 0 <= args.limit <= 100000:
                raise ValueError("Limit must be between 0 and 100000")
            if args.limit:
                sites = sites[: args.limit]
            results = []

            def receive(r):
                results.append(r)
                print(json.dumps(r.data(), ensure_ascii=False), flush=True)

            asyncio.run(scan(sites, args.cli, receive, threading.Event()))
            if args.output:
                export_results(args.output, args.cli, results)
            return
        from .desktop import run_desktop

        run_desktop(root)
    except KeyboardInterrupt:
        return
    except (OSError, ValueError) as exc:
        if not args.cli and sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, str(exc), "NIX", 0x10)
        print(f"NIX: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
