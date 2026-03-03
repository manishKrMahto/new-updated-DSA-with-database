#!/usr/bin/env python
"""
Manage script so you can run the app with:  python manage.py runserver
(Same style as Django's manage.py; this project uses Flask under the hood.)
"""
import argparse
import sys


def runserver(host=None, port=None, debug=True):
    from settings import DEFAULT_PORT, HOST, DEBUG
    from app import app
    app.run(host=host or HOST, port=port if port is not None else DEFAULT_PORT, debug=debug)


def main():
    parser = argparse.ArgumentParser(description="PBM Deep Research Agent")
    subparsers = parser.add_subparsers(dest="command", help="commands")

    runserver_parser = subparsers.add_parser("runserver", help="Start the Flask dev server")
    runserver_parser.add_argument("--host", default=None, help="Host to bind (default: 127.0.0.1; use 0.0.0.0 for network)")
    runserver_parser.add_argument("--port", type=int, default=None, help="Port (default: from config, 8000)")
    runserver_parser.add_argument("--no-debug", action="store_true", help="Disable debug mode")

    args = parser.parse_args()

    if args.command == "runserver":
        runserver(host=args.host, port=args.port, debug=not args.no_debug)
    else:
        parser.print_help()
        sys.exit(0 if not args.command else 1)


if __name__ == "__main__":
    main()
