def merge_collections_to_set(*args) -> set:
    out = set()
    for li in args:
        out.update(li)
    return out


def safe_remove(elements: list, element):
    if element in elements:
        elements.remove(element)


def remove_where(elements: list, cond):
    # Walk backwards: popping by ascending index would shift every later
    # element down and either skip entries or run off the end.
    for i in range(len(elements) - 1, -1, -1):
        if cond(elements[i]):
            elements.pop(i)
