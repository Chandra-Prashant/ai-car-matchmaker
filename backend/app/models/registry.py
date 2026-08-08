"""Single import point for every ORM model.

Importing this module guarantees Base.metadata knows about all tables, so
create_all() produces a complete schema. Anything that creates tables should
import this rather than remembering to import each model module — forgetting
one produces a database that is silently missing a table.
"""

from app.models.booking import Booking  # noqa: F401
from app.models.listing import Base, Listing  # noqa: F401
from app.state.store import SessionRow  # noqa: F401

__all__ = ["Base", "Booking", "Listing", "SessionRow"]
