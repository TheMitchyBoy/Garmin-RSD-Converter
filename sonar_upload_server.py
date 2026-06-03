#!/usr/bin/env python3
"""
Backward-compatible entry point for the sonar web upload UI.

Prefer ``main.py``, ``python sonar_cli.py serve``, or ``sonar_web_app`` for
new deployments (Railway, Docker, etc.).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

from sonar_web_app import resolve_port, run_web_app

__all__ = ['run_server', 'main']


def run_server(
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    uploads_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> None:
    """
    Start the web app (legacy signature).

    ``uploads_dir`` and ``output_dir`` are mapped under a shared data root.
    """
    if uploads_dir or output_dir:
        base = (uploads_dir or output_dir or Path('data')).resolve().parent
        if uploads_dir and output_dir and uploads_dir.resolve().parent != output_dir.resolve().parent:
            base = uploads_dir.resolve().parent
        data_dir = base
    else:
        data_dir = Path(os.environ.get('SONAR_DATA_DIR', 'data'))

    run_web_app(host=host, port=resolve_port(port), data_dir=data_dir)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description='Garmin Sonar RSD web upload server')
    parser.add_argument(
        '--host', default=os.environ.get('SONAR_HOST', '0.0.0.0'),
        help='Bind address (default: 0.0.0.0, or SONAR_HOST env)',
    )
    parser.add_argument(
        '--port', type=int, default=None,
        help='Port (default: PORT or SONAR_PORT env, else 8080)',
    )
    parser.add_argument(
        '--data-dir', type=Path, default=Path(os.environ.get('SONAR_DATA_DIR', 'data')),
        help='Data root for sessions (default: ./data or SONAR_DATA_DIR env)',
    )
    parser.add_argument(
        '--uploads-dir', type=Path, default=None,
        help='Legacy: parent data dir when uploads live under ./uploads',
    )
    parser.add_argument(
        '--output-dir', type=Path, default=None,
        help='Legacy: parent data dir when output lives under ./output',
    )

    args = parser.parse_args(argv)

    data_dir = args.data_dir
    if args.uploads_dir and args.uploads_dir.name == 'uploads':
        data_dir = args.uploads_dir.parent
    if args.output_dir and args.output_dir.name == 'output':
        data_dir = args.output_dir.parent

    run_web_app(host=args.host, port=resolve_port(args.port), data_dir=data_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
