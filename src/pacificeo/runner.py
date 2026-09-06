import argparse
import subprocess
from pathlib import Path

from sqlalchemy import text

from pacificeo.db import SessionLocal
from pacificeo.settings import get_settings


def next_run(mode: str) -> str | None:
    settings = get_settings()
    age_filter = "" if mode == "primary" else "and created_at <= now() - make_interval(mins => :grace)"
    with SessionLocal.begin() as session:
        return session.execute(text(f"""
            select id::text from runs where status='queued' and run_type='processing'
            {age_filter} order by created_at for update skip locked limit 1
        """), {"grace":settings.primary_grace_minutes}).scalar_one_or_none()


def dispatch_once(mode: str) -> bool:
    run_id = next_run(mode)
    if not run_id:
        return False
    project = Path(__file__).resolve().parents[2]
    command = ["uv", "run", "--isolated", "--project", str(project), "python", "-m", "pacificeo.worker", "--run-id", run_id]
    subprocess.run(command, check=True)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("primary", "cloud"), default="primary")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while dispatch_once(args.mode) and not args.once:
        pass
