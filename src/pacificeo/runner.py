import argparse
import subprocess
from pathlib import Path

from sqlalchemy import text

from pacificeo.db import SessionLocal
from pacificeo.settings import get_settings


def claim_next_run(mode: str) -> str | None:
    settings = get_settings()
    age_filter = (
        ""
        if mode == "primary"
        else "and created_at <= now() - make_interval(mins => :grace)"
    )
    with SessionLocal.begin() as session:
        return session.execute(
            text(f"""
                with candidate as (
                    select id from runs
                    where run_type='processing'
                      and (
                        status='queued'
                        or (status='running' and lease_expires_at < now())
                      )
                      {age_filter}
                    order by created_at
                    for update skip locked
                    limit 1
                )
                update runs r
                set status='running', runner=:runner, started_at=coalesce(started_at, now()),
                    claimed_by=:runner,
                    lease_expires_at=now() + make_interval(mins => :lease),
                    attempt_count=attempt_count + 1
                from candidate
                where r.id=candidate.id
                returning r.id::text
            """),
            {
                "grace": settings.primary_grace_minutes,
                "lease": settings.runner_lease_minutes,
                "runner": mode,
            },
        ).scalar_one_or_none()


def dispatch_once(mode: str) -> bool:
    run_id = claim_next_run(mode)
    if not run_id:
        return False
    project = Path(__file__).resolve().parents[2]
    command = [
        "uv",
        "run",
        "--isolated",
        "--project",
        str(project),
        "python",
        "-m",
        "pacificeo.worker",
        "--run-id",
        run_id,
    ]
    subprocess.run(command, check=True)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("primary", "cloud"), default="primary")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while dispatch_once(args.mode) and not args.once:
        pass
