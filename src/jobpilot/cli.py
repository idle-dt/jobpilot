"""CLI interface for JobPilot."""

import click

from jobpilot.config import settings


@click.group()
@click.version_option(package_name="jobpilot")
@click.pass_context
def cli(ctx: click.Context):
    """JobPilot — local job search autopilot."""
    # init-db is the one command whose job is to create a database, so it is the
    # only one allowed past a missing explicitly-configured path.
    if ctx.invoked_subcommand != "init-db":
        error = settings.missing_db_error()
        if error:
            raise click.ClickException(error)
    settings.ensure_dirs()


@cli.command()
def serve():
    """Start the web UI server."""
    from jobpilot.web.app import create_app

    app = create_app()
    app.run(
        host=settings.server_host, port=settings.server_port,
        debug=settings.debug, threaded=True,
    )


@cli.command()
@click.option(
    "--days", default=None, type=int,
    help="Fetch emails from the last N days (default: from DB setting).",
)
@click.option("--max-results", default=200, help="Maximum number of emails to fetch.")
def fetch(days: int | None, max_results: int):
    """Fetch new emails from Gmail."""
    import logging
    from datetime import datetime, timedelta

    from jobpilot.gmail.client import GmailClient
    from jobpilot.gmail.fetcher import fetch_new_emails
    from jobpilot.storage.database import init_db
    from jobpilot.storage.repository import Repository

    logging.basicConfig(level=settings.log_level)
    creds = _require_credentials()

    conn = init_db(settings.db_path)
    repo = Repository(conn)
    if days is None:
        days = int(repo.get_setting("sync_days", "7"))

    since = datetime.now() - timedelta(days=days)
    click.echo(f"Fetching emails from the last {days} days...")
    result = fetch_new_emails(
        GmailClient(creds), repo, since=since, max_results=max_results,
        on_quota_wait=_echo_quota_wait,
    )

    click.echo(f"Done. {result.new_emails} new emails stored.")
    if result.truncated:
        click.echo(f"Incomplete: {result.processed}/{result.total} handled. Run fetch again.")
    conn.close()


def _require_credentials():
    """Return Gmail credentials, exiting with a hint if the user has not authenticated."""
    from jobpilot.gmail.auth import GmailAuth

    auth = GmailAuth(settings.gmail_credentials_path, settings.gmail_token_path)
    if not auth.is_authenticated():
        click.echo("Not authenticated. Run 'jobpilot setup' first.")
        raise SystemExit(1)
    return auth.get_credentials()


def _echo_quota_wait(processed: int, total: int) -> None:
    """Tell the user why a fetch has gone quiet, so it does not look hung."""
    click.echo(
        f"Gmail rate limit reached at {processed}/{total} — "
        "waiting for the quota to refill…"
    )


@cli.command()
def scrape():
    """Scrape job boards for new listings."""
    click.echo("Scraping not yet implemented.")


@cli.command()
def setup():
    """Set up Gmail OAuth credentials."""
    from google.auth.exceptions import GoogleAuthError

    from jobpilot.gmail.auth import GmailAuth

    auth = GmailAuth(settings.gmail_credentials_path, settings.gmail_token_path)

    if not settings.gmail_credentials_path.exists():
        click.echo(f"credentials.json not found at {settings.gmail_credentials_path}")
        click.echo("Download it from Google Cloud Console and place it there.")
        raise SystemExit(1)

    if auth.is_authenticated():
        click.echo("Already authenticated!")
        return

    click.echo("Opening browser for Google authentication...")
    try:
        auth.get_credentials()
        click.echo("Authentication successful!")
        click.echo(f"Token saved to: {settings.gmail_token_path}")
    except (FileNotFoundError, OSError, ValueError, GoogleAuthError) as e:
        click.echo(f"Authentication failed: {e}")
        raise SystemExit(1) from e


@cli.command()
def stats():
    """Show classification and application statistics."""
    from jobpilot.storage.database import init_db
    from jobpilot.storage.repository import Repository

    conn = init_db(settings.db_path)
    repo = Repository(conn)
    email_stats = repo.get_email_stats()

    click.echo(f"Emails: {email_stats['total']} total, {email_stats['processed']} processed")
    click.echo(f"Labels: {email_stats['labeled']}")
    if email_stats["by_platform"]:
        click.echo("By platform:")
        for platform, count in email_stats["by_platform"].items():
            click.echo(f"  {platform or 'unknown'}: {count}")

    app_stats = repo.count_applications_by_status()
    if app_stats:
        click.echo("Applications:")
        for status, count in app_stats.items():
            click.echo(f"  {status}: {count}")

    conn.close()


@cli.command()
def init_db_cmd():
    """Initialize the database (creates tables if needed)."""
    from jobpilot.storage.database import init_db

    conn = init_db(settings.db_path)
    click.echo(f"Database initialized at {settings.db_path}")
    conn.close()


# The confidence floor is a CLI-level policy: the repository writes whatever it is
# handed, so the bar for trusting a machine-authored judgment lives here.
DEFAULT_MIN_CONFIDENCE = 0.95
ASSISTANT_LABEL_SOURCE = "assistant"


def _open_repo():
    """Open the database and return (connection, repository)."""
    from jobpilot.storage.database import init_db
    from jobpilot.storage.repository import Repository

    conn = init_db(settings.db_path)
    return conn, Repository(conn)


def _echo_ids(label: str, ids: list[int]) -> None:
    """Print a labelled id list, truncated so a large run stays readable."""
    from jobpilot.services.label_service import MAX_LISTED_IDS

    shown = ids[:MAX_LISTED_IDS]
    hidden = len(ids) - len(shown)
    more = f", … (+{hidden} more)" if hidden else ""
    click.echo(f"{label}: {len(ids)} — {', '.join(str(i) for i in shown)}{more}")


def _echo_run(run, verb: str) -> None:
    """Print a one-line summary of a bulk run, its coverage, and its audit log path."""
    prefix = "Dry run — nothing written. " if run.dry_run else ""
    passed = f", {run.passed} passed to you" if run.passed else ""
    tracked = f", {run.tracked} tracked" if run.tracked else ""
    click.echo(
        f"{prefix}{verb}: {run.applied} applied{passed}{tracked},"
        f" {run.rejected} rejected ({run.below_threshold} below threshold)"
    )
    if run.queue_size:
        if run.unaccounted:
            _echo_ids(f"Coverage: {run.queue_size} in queue — unaccounted", run.unaccounted)
        else:
            click.echo(f"Coverage: {run.queue_size} in queue — all accounted for")
    if run.conflicts:
        _echo_ids(
            "Rules need updating — produced labels you already cancelled", run.conflicts,
        )
    click.echo(f"Audit log: {run.log_path}")


@cli.command("label-batch")
@click.option(
    "--input", "input_path", required=True, type=click.Path(exists=True),
    help="JSONL file of {id, label, confidence, reason} entries.",
)
@click.option(
    "--min-confidence", default=DEFAULT_MIN_CONFIDENCE, type=float,
    help="Reject entries whose stated confidence falls below this floor.",
)
@click.option("--dry-run", is_flag=True, help="Report the outcome without writing.")
@click.option("--force", is_flag=True, help="Overwrite jobs that already carry a label.")
def label_batch(input_path: str, min_confidence: float, dry_run: bool, force: bool) -> None:
    """Apply labels from a JSONL file produced by a bulk labeling run."""
    from pathlib import Path

    from jobpilot.services.label_service import LabelBatchService

    conn, repo = _open_repo()
    service = LabelBatchService(repo, settings.db_path.parent)
    run = service.run_batch(Path(input_path), min_confidence, dry_run, force)
    _echo_run(run, "Labels")
    conn.close()


@cli.command("label-report")
@click.option(
    "--output", "output_path", default=None, type=click.Path(),
    help="Where to write the review document (default: docs/label-queue-result.md).",
)
def label_report(output_path: str | None) -> None:
    """Write a Markdown review of every label a bulk run has applied."""
    from pathlib import Path

    from jobpilot.services.label_report import DEFAULT_REPORT_PATH, write_label_report

    conn, repo = _open_repo()
    target = Path(output_path) if output_path else DEFAULT_REPORT_PATH
    written = write_label_report(repo, target)
    click.echo(f"Review written to {written}")
    conn.close()


@cli.command("label-revert")
@click.option(
    "--source", default=ASSISTANT_LABEL_SOURCE,
    help="Clear only labels authored by this source.",
)
@click.option("--dry-run", is_flag=True, help="Report what would be cleared, write nothing.")
def label_revert(source: str, dry_run: bool) -> None:
    """Clear every label written by one author, leaving the others untouched."""
    from jobpilot.services.label_service import LabelBatchService

    conn, repo = _open_repo()
    run = LabelBatchService(repo, settings.db_path.parent).revert(source, dry_run)
    _echo_run(run, f"Cleared '{source}' labels")
    conn.close()


@cli.command("label-export")
@click.option(
    "--output", "output_path", required=True, type=click.Path(),
    help="Where to write the queue JSON a labeling run reads.",
)
def label_export(output_path: str) -> None:
    """Write every job awaiting a verdict as JSON, with the labels you have cancelled.

    This is the tool-neutral entry point: an agent needs no SQL and no knowledge of
    which columns define the queue. See docs/labeling-prompt.md.
    """
    import json
    from pathlib import Path

    conn, repo = _open_repo()
    rows = repo.export_rows()
    target = Path(output_path)
    target.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    click.echo(f"Exported {len(rows)} job(s) to {target}")
    conn.close()


@cli.command("passed-reset")
@click.option("--dry-run", is_flag=True, help="Report what would be cleared, write nothing.")
def passed_reset(dry_run: bool) -> None:
    """Clear every hand-back so the next run reconsiders those jobs.

    Run this after rewriting docs/labeling-criteria.md: jobs passed over under the old
    rules deserve a fresh look under the new ones. Labels are never touched.
    """
    from jobpilot.services.label_service import LabelBatchService

    conn, repo = _open_repo()
    run = LabelBatchService(repo, settings.db_path.parent).reset_passed(dry_run)
    _echo_run(run, "Cleared hand-backs")
    conn.close()
