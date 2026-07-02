from __future__ import annotations

import logging
from pathlib import Path

from pynetdicom import AE, ALL_TRANSFER_SYNTAXES, AllStoragePresentationContexts, evt
from pynetdicom.sop_class import (
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelMove,
    Verification,
)

from .bootstrap import ensure_schema
from .config import Settings
from .db import Database
from .pacs_catalog import (
    build_find_dataset,
    find_matches,
    load_dataset,
    move_contexts,
    retrieve_matches,
    store_instance,
)


LOGGER = logging.getLogger("raiox_pacs.dicom")


def _ae_title_from_event(event) -> str:
    value = getattr(event.assoc.requestor, "ae_title", b"")
    if isinstance(value, bytes):
        return value.decode("ascii", errors="ignore").strip()
    return str(value or "").strip()


def handle_echo(event):
    return 0x0000


def handle_store(event, database: Database, settings: Settings):
    try:
        store_instance(database, settings, event.dataset, event.file_meta, source_ae=_ae_title_from_event(event))
    except ValueError as exc:
        LOGGER.error("Dataset DICOM invalido: %s", exc)
        return 0xC210
    except Exception:
        LOGGER.exception("Falha ao persistir instancia DICOM.")
        return 0xA700
    return 0x0000


def handle_find(event, database: Database, settings: Settings):
    if event.identifier is None:
        yield 0xA900, None
        return
    try:
        level, rows = find_matches(database, event.identifier)
    except ValueError:
        yield 0xA900, None
        return
    except Exception:
        LOGGER.exception("Falha na consulta C-FIND.")
        yield 0xC320, None
        return

    for row in rows:
        if event.is_cancelled:
            yield 0xFE00, None
            return
        yield 0xFF00, build_find_dataset(level, row, settings.pacs_aet)

    yield 0x0000, None


def handle_get(event, database: Database, settings: Settings):
    if event.identifier is None:
        yield 0xA900, None
        return
    try:
        rows = retrieve_matches(database, event.identifier)
    except ValueError:
        yield 0xA900, None
        return
    except Exception:
        LOGGER.exception("Falha na consulta C-GET.")
        yield 0xC420, None
        return

    yield len(rows)
    for row in rows:
        if event.is_cancelled:
            yield 0xFE00, None
            return
        try:
            yield 0xFF00, load_dataset(row["filepath"])
        except Exception:
            LOGGER.exception("Falha ao ler instancia para C-GET: %s", row.get("filepath"))
            yield 0xC421, None


def handle_move(event, database: Database, settings: Settings):
    if event.identifier is None:
        yield 0xA900, None
        return
    move_destination = event.move_destination
    key = move_destination.decode("ascii", errors="ignore").strip().upper() if isinstance(move_destination, bytes) else str(move_destination or "").strip().upper()
    target = settings.move_destinations.get(key)
    if not target or len(target) < 2:
        yield None, None
        return

    try:
        rows = retrieve_matches(database, event.identifier)
    except ValueError:
        yield 0xA900, None
        return
    except Exception:
        LOGGER.exception("Falha na consulta C-MOVE.")
        yield 0xC520, None
        return

    contexts = move_contexts(rows)
    yield str(target[0]), int(target[1]), {"contexts": contexts}
    yield len(rows)
    for row in rows:
        if event.is_cancelled:
            yield 0xFE00, None
            return
        try:
            yield 0xFF00, load_dataset(row["filepath"])
        except Exception:
            LOGGER.exception("Falha ao ler instancia para C-MOVE: %s", row.get("filepath"))
            yield 0xC521, None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    project_root = Path(__file__).resolve().parent.parent
    settings = Settings.load(project_root)
    database = Database(settings)
    if settings.auto_bootstrap_schema:
        ensure_schema(database)

    ae = AE(ae_title=settings.pacs_aet)
    ae.add_supported_context(Verification, ALL_TRANSFER_SYNTAXES)
    for cx in AllStoragePresentationContexts:
        ae.add_supported_context(cx.abstract_syntax, ALL_TRANSFER_SYNTAXES, scp_role=True, scu_role=False)
    ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
    ae.add_supported_context(StudyRootQueryRetrieveInformationModelGet)
    ae.add_supported_context(StudyRootQueryRetrieveInformationModelMove)

    handlers = [
        (evt.EVT_C_ECHO, handle_echo),
        (evt.EVT_C_STORE, handle_store, [database, settings]),
        (evt.EVT_C_FIND, handle_find, [database, settings]),
        (evt.EVT_C_GET, handle_get, [database, settings]),
        (evt.EVT_C_MOVE, handle_move, [database, settings]),
    ]

    LOGGER.info(
        "Starting DICOM PACS on %s:%s with AE=%s",
        settings.dicom_bind_host,
        settings.dicom_port,
        settings.pacs_aet,
    )
    ae.start_server((settings.dicom_bind_host, settings.dicom_port), evt_handlers=handlers, block=True)


if __name__ == "__main__":
    main()
