def merge_collections_to_set(*args) -> set:
    out = set()
    for li in args:
        out.update(li)
    return out


def safe_remove(elements: list, element):
    if element in elements:
        elements.remove(element)


def remove_where(elements: list, cond):
    to_remove_indexes = []
    for i, val in enumerate(elements):
        if cond(val):
            to_remove_indexes.append(i)

    for i in to_remove_indexes:
        elements.pop(i)
