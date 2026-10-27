"""`crystalline` console script entry point."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import uuid
from collections.abc import Sequence

from crystalline.project import (
    apply_extensions,
    build_agent,
    end_monitoring_session,
    load_project,
    start_monitoring_session,
)
from crystalline.security import authenticate, bind_token

from .console import console, print_error
from .repl import run_repl


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crystalline",
        description="Talk to a Crystalline project from the command line.",
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Path to a project config file (.yaml/.yml/.json).",
    )
    parser.add_argument("--user", help="Username to log in as. Prompted if omitted.")
    parser.add_argument(
        "--password", help="Password for --user. Prompted (hidden) if omitted."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    project = load_project(args.project)

    try:
        apply_extensions(project)
    except Exception as exc:
        print_error(f"Failed to load tools/skills: {exc}")
        return 1

    if args.user is not None:
        username = args.user
    else:
        console.print("[prompt]Username:[/prompt] ", end="")
        username = input()

    if args.password is not None:
        password = args.password
    else:
        console.print("[prompt]Password:[/prompt] ", end="")
        password = getpass.getpass("")

    try:
        user = authenticate(project.storage, username, password)
    except PermissionError as exc:
        print_error(str(exc))
        return 1

    token = project.security.mint_token(user)
    session_id = uuid.uuid4().hex
    start_monitoring_session(project, session_id, principal=user.id)
    agent = build_agent(project, session_id=session_id)

    try:
        with bind_token(token):
            asyncio.run(
                run_repl(project, agent, project_path=args.project, session_id=session_id)
            )
    except KeyboardInterrupt:
        console.print()
        return 130
    finally:
        end_monitoring_session(project, session_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
