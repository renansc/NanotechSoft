from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from raiox_pacs.bootstrap import ensure_schema
from raiox_pacs.config import Settings
from raiox_pacs.db import Database


def main() -> None:
    settings = Settings.load(ROOT_DIR)
    database = Database(settings)
    ensure_schema(database)
    print("Schema raiox inicializado com sucesso.")


if __name__ == "__main__":
    main()
