"""Command line interface: ask, chat, validate, search, serve, telegram."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .engine import Bot, ChatSession
from .kb import KnowledgeBaseError, load_kb

DEFAULT_KB = os.environ.get("FAQBOT_KB", "kb.yaml")


def _print_answer(answer, *, show_meta: bool = True) -> None:
    print(answer.text)
    if show_meta:
        meta = f"  [{answer.intent}, score={answer.score:.2f}"
        if answer.qa_id:
            meta += f", qa_id={answer.qa_id}"
        print(meta + "]")


def _cmd_ask(args: argparse.Namespace) -> int:
    bot = Bot(load_kb(args.kb))
    answer = bot.ask(args.question)
    if args.json:
        print(json.dumps(answer.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_answer(answer)
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    bot = Bot(load_kb(args.kb))
    matches = bot.find(args.query, limit=args.limit)
    if not matches:
        print("No matches.")
        return 1
    for match in matches:
        print(f"{match.score:.3f}  #{match.item.id:<4} {match.item.question}")
        print(f"       category={match.item.category or '-'}")
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    bot = Bot(load_kb(args.kb))
    session = ChatSession()
    print(f"{bot.settings.bot_name}: {bot.settings.greeting}")
    print("Type your question, Ctrl+C or 'exit' to stop.\n")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if text.lower() in {"exit", "quit", "выход"}:
            return 0
        if not text:
            continue
        answer = bot.respond(session, text)
        print(f"bot> {answer.text}")
        if answer.quick:
            labels = " | ".join(chip.label for chip in answer.quick)
            print(f"     quick: {labels}")
        print(f"     [{answer.intent}, score={answer.score:.2f}]\n")


def _cmd_validate(args: argparse.Namespace) -> int:
    kb = load_kb(args.kb)
    warnings = kb.validate()
    categories = kb.categories()
    print(f"OK: {len(kb.items)} QA entries, {len(categories)} categories")
    if categories:
        print("Categories: " + ", ".join(categories))
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if warnings and args.strict:
        return 1
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("Install the API extra first: pip install 'faqbot[api]'", file=sys.stderr)
        return 1

    from .api import create_app

    app = create_app(
        args.kb,
        unanswered_path=args.unanswered,
        feedback_path=args.feedback,
        cors_origins=tuple(args.cors) if args.cors else ("*",),
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _cmd_telegram(args: argparse.Namespace) -> int:
    from .telegram import run

    run(args.kb, token=args.token)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="faqbot",
        description="Offline FAQ chatbot: match questions against a YAML knowledge base.",
    )
    parser.add_argument("--version", action="version", version=f"faqbot {__version__}")
    parser.add_argument(
        "--kb",
        default=DEFAULT_KB,
        help=f"path to knowledge base YAML/JSON (default: {DEFAULT_KB})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="ask one question")
    ask.add_argument("question", help="text of the question")
    ask.add_argument("--json", action="store_true", help="print the full answer as JSON")
    ask.set_defaults(func=_cmd_ask)

    search = sub.add_parser("search", help="show raw match scores")
    search.add_argument("query")
    search.add_argument("-n", "--limit", type=int, default=5)
    search.set_defaults(func=_cmd_search)

    chat = sub.add_parser("chat", help="interactive dialogue in the terminal")
    chat.set_defaults(func=_cmd_chat)

    validate = sub.add_parser("validate", help="check the knowledge base")
    validate.add_argument("--strict", action="store_true", help="fail on warnings")
    validate.set_defaults(func=_cmd_validate)

    serve = sub.add_parser("serve", help="run the HTTP API and demo widget")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--unanswered", default="var/unanswered.jsonl")
    serve.add_argument("--feedback", default="var/feedback.jsonl")
    serve.add_argument(
        "--cors",
        action="append",
        default=[],
        help="allowed origin (repeatable, default: *)",
    )
    serve.set_defaults(func=_cmd_serve)

    telegram = sub.add_parser("telegram", help="run the Telegram adapter (long polling)")
    telegram.add_argument("--token", default=os.environ.get("FAQBOT_TELEGRAM_TOKEN", ""))
    telegram.set_defaults(func=_cmd_telegram)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KnowledgeBaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
