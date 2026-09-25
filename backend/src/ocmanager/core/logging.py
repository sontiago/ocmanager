import logging
import sys
from collections.abc import MutableMapping
from typing import Any, Literal

import structlog
from structlog.typing import EventDict, Processor

SENSITIVE_KEYS = frozenset(
    {"token", "password", "secret", "authorization", "init_data", "initdata", "cookie"}
)
SENSITIVE_SUFFIXES = ("_token", "_password", "_secret", "_key")
REDACTED = "***"


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return k in SENSITIVE_KEYS or k.endswith(SENSITIVE_SUFFIXES)


def _redact_value(value: Any) -> Any:
    if isinstance(value, MutableMapping):
        return {
            k: REDACTED if _is_sensitive(str(k)) else _redact_value(v) for k, v in value.items()
        }
    return value


def redact(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """Заменяет значения секретных ключей на ***, в том числе во вложенных словарях."""
    return {k: REDACTED if _is_sensitive(k) else _redact_value(v) for k, v in event_dict.items()}


def configure_logging(level: str, *, fmt: Literal["json", "console"] = "json") -> None:
    """Один формат для structlog и stdlib (uvicorn, sqlalchemy, arq): всё в stdout."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact,
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    final: list[Processor] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if fmt == "json":
        final.append(structlog.processors.dict_tracebacks)
    final.append(renderer)

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(foreign_pre_chain=shared, processors=final)
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn ставит свои обработчики до вызова фабрики приложения — снимаем их,
    # чтобы его строки шли через тот же JSON-рендерер.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
