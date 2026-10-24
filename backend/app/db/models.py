"""Import every model module so metadata is complete (Alembic, mappers)."""
from app.licensing import models as _licensing  # noqa: F401
from app.modules.org import models as _org  # noqa: F401
from app.modules.library import models as _library  # noqa: F401
from app.modules.crm import models as _crm  # noqa: F401
from app.modules.sales import models as _sales  # noqa: F401
from app.modules.production import models as _production  # noqa: F401
from app.modules.inventory import models as _inventory  # noqa: F401
from app.modules.purchasing import models as _purchasing  # noqa: F401
from app.modules.treasury import models as _treasury  # noqa: F401
