"""Shared pagination for list endpoints (P1.6): `?page=&page_size=` query
params plus an `X-Total-Count` response header, so a route only has to
apply `.offset()/.limit()` to its own query and report the total -- no
per-route boilerplate for parsing/validating the params.

Applied by default (not opt-in): omitting the params still returns page 1
at the default size, not the full unbounded set -- that's the point of this
fix (see master spec P1.6/G7). Callers that genuinely need everything (CSV
export, send-time recipient iteration, etc.) query the model directly
instead of going through the paginated endpoint.
"""
from fastapi import Query, Response

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class Pagination:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def paginate(query, pagination: Pagination, response: Response) -> list:
    """Applies `pagination` to `query`, sets X-Total-Count on `response`
    from the pre-limit count, and returns the page's rows."""
    total = query.order_by(None).count()  # ORDER BY is irrelevant to (and can break) a COUNT query
    response.headers["X-Total-Count"] = str(total)
    return query.offset(pagination.offset).limit(pagination.page_size).all()
