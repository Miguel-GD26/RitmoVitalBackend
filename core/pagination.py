"""
core.pagination — Metadata de paginación compatible con el cliente Angular.
"""

import math


def build_pagination_metadata(total_items, page=1, page_size=100):
    """Metadata de paginación sobre una lista Python (no requiere queryset)."""
    total_pages = max(1, math.ceil(total_items / page_size))
    page = max(1, min(page, total_pages))

    return {
        "count": total_items,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }


def paginate_list(items, page=1, page_size=100):
    """Pagina una lista Python. Retorna (items_pagina, metadata_dict)."""
    total = len(items)
    metadata = build_pagination_metadata(total, page, page_size)

    start = (metadata["page"] - 1) * page_size
    end = start + page_size
    page_items = items[start:end]

    return page_items, metadata
