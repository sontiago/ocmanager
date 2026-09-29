import typer

from ocmanager.cli._common import db_session, run, settings
from ocmanager.core.clock import utcnow
from ocmanager.flows.reconcile import reconcile_all
from ocmanager.provisioning.pki.ca import load_ca


def reconcile() -> None:
    """Сверить ноды с БД сейчас, как cron воркера: починить и показать найденные дрейфы."""

    async def go() -> None:
        s = settings()
        async with db_session() as session:
            reports = await reconcile_all(session, s, load_ca(s.pki_dir), utcnow())
            await session.commit()
        for report in reports:
            typer.echo(
                f"нода {report.node_id}: " + ("расхождений нет" if not report.drifts else "")
            )
            for drift in report.drifts:
                typer.echo(f"  {drift.kind}: {drift.details}")
            if report.error:
                typer.echo(f"  ошибка: {report.error}")

    run(go)
