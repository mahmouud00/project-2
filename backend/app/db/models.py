"""Import every model module so metadata is complete (Alembic, mappers)."""
from app.licensing import models as _licensing  # noqa: F401
from app.modules.org import models as _org  # noqa: F401
