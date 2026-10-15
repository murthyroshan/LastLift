"""FalkorDB connection. One client per process; graphs are selected by logical name."""
from functools import lru_cache

from falkordb import FalkorDB

from .config import settings


@lru_cache(maxsize=1)
def client() -> FalkorDB:
    return FalkorDB(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        username=settings.falkordb_username,
        password=settings.falkordb_password,
        socket_timeout=10,
        socket_connect_timeout=5,
    )


def graph(name: str):
    """Select a graph by logical name ('base', 'demo', 'live', ...)."""
    return client().select_graph(settings.graph(name))


def ping() -> bool:
    try:
        return bool(client().connection.ping())
    except Exception:
        return False


def module_version() -> str | None:
    try:
        for mod in client().connection.execute_command("MODULE", "LIST"):
            fields = {(mod[i].decode() if isinstance(mod[i], bytes) else mod[i]): mod[i + 1] for i in range(0, len(mod), 2)}
            name = fields.get("name")
            name = name.decode() if isinstance(name, bytes) else name
            if name and "graph" in name.lower():
                v = int(fields["ver"])
                return f"{v // 10000}.{(v // 100) % 100}.{v % 100}"
    except Exception:
        return None
    return None
