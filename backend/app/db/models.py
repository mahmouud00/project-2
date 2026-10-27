"""Import every model module so metadata is complete (Alembic, mappers)."""
from app.licensing import models as _licensing  # noqa: F401
from app.modules.org import models as _org  # noqa: F401
from app.modules.library import models as _library  # noqa: F401
from app.modules.crm import models as _crm  # noqa: F401
from app.modules.sales import models as _sales  # noqa: F401
from app.modules.production import models as _production  # noqa: F401
from app.modules.purchasing import models as _purchasing  # noqa: F401
from app.modules.treasury import models as _treasury  # noqa: F401
from app.modules.invoicing import models as _invoicing  # noqa: F401
from app.modules.field import models as _field  # noqa: F401
from app.modules.hr import models as _hr  # noqa: F401
from app.modules.finance import models as _finance  # noqa: F401
