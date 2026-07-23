from ansible.errors import AnsibleFilterError


def merge_mapping(list1, list2, key_name="source"):
    """
    Merge two lists of dicts on a given key.
    - list1, list2: each must be a List[Dict]
    - key_name: the field to match on
    If both lists contain an item with the same key_name value,
    their dictionaries are merged (fields from list2 overwrite or add to list1).
    """
    if not isinstance(list1, list) or not isinstance(list2, list):
        raise AnsibleFilterError("merge_mapping expects two lists")

    merged = {}
    for item in list1:
        if key_name not in item:
            raise AnsibleFilterError(f"Item {item} is missing the key '{key_name}'")
        merged[item[key_name]] = item.copy()

    for item in list2:
        if key_name not in item:
            raise AnsibleFilterError(f"Item {item} is missing the key '{key_name}'")
        k = item[key_name]
        if k in merged:
            merged[k].update(item)
        else:
            merged[k] = item.copy()

    return list(merged.values())


class FilterModule:
    def filters(self):
        return {
            "merge_mapping": merge_mapping,
        }
