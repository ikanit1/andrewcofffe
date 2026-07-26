"""Применение обновления прямо из админки.

Обновляется только код: pos.db лежит в .gitignore, git её не трогает. Перед
работой всё равно делается копия базы — если новая версия поменяет схему,
будет к чему вернуться.

Перезапуск возможен не всегда. deploy/run-server.ps1 держит сервер в цикле
и поднимает его снова через несколько секунд после выхода — там достаточно
завершить процесс. При ручном запуске через start.ps1 такого надзора нет,
и тогда мы честно просим перезапустить кассу руками, а не оставляем
владельца с погашенным экраном.
"""
import asyncio
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.shift_service import current_open_shift

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_RESTART_DELAY_SECONDS = 1.5
_COMMAND_TIMEOUT_SECONDS = 180


@dataclass
class UpdateResult:
    ok: bool
    message: str
    log: str = ""
    restart_scheduled: bool = False
    steps: list[str] = field(default_factory=list)


def is_supervised() -> bool:
    """True — процесс запущен под надзором run-server.ps1, который его поднимет."""
    return os.environ.get("COFFEEPOS_SUPERVISED") == "1"


async def _default_runner(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=_COMMAND_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, f"Команда {' '.join(cmd)} не уложилась в {_COMMAND_TIMEOUT_SECONDS} с"
    return proc.returncode or 0, out.decode("utf-8", errors="replace")


def _backup_database(root: Path) -> str | None:
    db = root / "pos.db"
    if not db.exists():
        return None
    backups = root / "backups"
    backups.mkdir(exist_ok=True)
    dst = backups / f"pos-before-update-{datetime.now():%Y-%m-%d_%H%M%S}.db"
    shutil.copy2(db, dst)
    return dst.name


async def apply_update(session: Session, *, runner=None, root: Path | None = None) -> UpdateResult:
    """Тянет код и ставит зависимости. Перезапуск сюда не входит — его планирует UI."""
    run = runner or _default_runner
    root = Path(root) if root is not None else PROJECT_ROOT
    steps: list[str] = []

    if current_open_shift(session) is not None:
        return UpdateResult(
            ok=False,
            message="Сначала закройте смену: перезапуск оборвал бы работу кассира.",
        )

    if not (root / ".git").exists():
        return UpdateResult(
            ok=False,
            message="Это установка из ZIP-архива — обновлять нечем, истории git нет. "
                    "Скачайте свежий архив на GitHub и распакуйте поверх папки: "
                    "база, .env и бэкапы в архиве отсутствуют, данные не пострадают.",
        )

    copy_name = _backup_database(root)
    if copy_name:
        steps.append(f"Копия базы: backups/{copy_name}")

    code, out = await run(["git", "pull", "--ff-only"], root)
    log = out.strip()
    if code != 0:
        return UpdateResult(
            ok=False,
            message="Не удалось забрать новую версию — код остался прежним, "
                    "перезапуска не будет.",
            log=log,
            steps=steps,
        )
    steps.append("Код обновлён")

    if (root / "requirements.txt").exists():
        pip_code, pip_out = await run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"], root
        )
        log = f"{log}\n{pip_out.strip()}".strip()
        if pip_code != 0:
            return UpdateResult(
                ok=False,
                message="Код обновлён, но зависимости поставить не удалось. "
                        "Перезапуск отменён — запустите update.ps1 с моноблока.",
                log=log,
                steps=steps,
            )
        steps.append("Зависимости актуальны")

    if is_supervised():
        return UpdateResult(
            ok=True,
            message="Обновлено. Касса перезапускается — страница обновится сама.",
            log=log, restart_scheduled=True, steps=steps,
        )
    return UpdateResult(
        ok=True,
        message="Обновлено. Перезапустите кассу вручную: закройте окно start.ps1 "
                "и запустите его снова — сейчас сервер работает без автоперезапуска.",
        log=log, restart_scheduled=False, steps=steps,
    )


def schedule_restart() -> None:
    """Выходит из процесса, чтобы run-server.ps1 поднял его заново.

    С задержкой: иначе ответ на текущий запрос не успеет уйти в браузер,
    и владелец увидит оборванное соединение вместо сообщения об успехе.
    """
    async def _bye() -> None:
        await asyncio.sleep(_RESTART_DELAY_SECONDS)
        logger.info("Перезапуск после обновления")
        os._exit(0)

    asyncio.create_task(_bye())
