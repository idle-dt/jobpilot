"""CLI interface for JobPilot."""

import click

from jobpilot.config import settings


@click.group()
@click.version_option(package_name="jobpilot")
def cli():
    """JobPilot — local job search autopilot."""
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

    from jobpilot.gmail.auth import GmailAuth
    from jobpilot.gmail.client import GmailClient
    from jobpilot.gmail.fetcher import fetch_new_emails
    from jobpilot.storage.database import init_db
    from jobpilot.storage.repository import Repository

    logging.basicConfig(level=settings.log_level)

    auth = GmailAuth(settings.gmail_credentials_path, settings.gmail_token_path)
    if not auth.is_authenticated():
        click.echo("Not authenticated. Run 'jobpilot setup' first.")
        raise SystemExit(1)

    conn = init_db(settings.db_path)
    repo = Repository(conn)

    if days is None:
        days = int(repo.get_setting("sync_days", "7"))

    creds = auth.get_credentials()
    client = GmailClient(creds)

    since = datetime.now() - timedelta(days=days)
    click.echo(f"Fetching emails from the last {days} days...")

    count = fetch_new_emails(client, repo, since=since, max_results=max_results)
    click.echo(f"Done. {count} new emails stored.")
    conn.close()


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
