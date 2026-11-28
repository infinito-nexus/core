def first_seen_merge(registry, cards, today):
    """Record the first-deploy date of every card the registry does not know yet.

    Args:
        registry: the stored ``{application_id: date}`` mapping, or None when
            the host has none yet; on that first run every card becomes a
            baseline entry with an empty date, so a fresh host shows no card as new.
        cards: output of the ``docker_cards`` lookup.
        today: the ISO date of this deploy.

    Returns:
        The registry with an entry for every card.
    """
    stamp = "" if registry is None else today
    merged = dict(registry or {})
    for card in cards:
        merged.setdefault(card["id"], stamp)
    return merged


def with_added(cards, registry):
    """Attach ``added`` to every card whose first-deploy date the registry holds.

    Args:
        cards: output of the ``docker_cards`` lookup.
        registry: output of ``first_seen_merge``.
    """
    return [
        {**card, "added": registry[card["id"]]} if registry.get(card["id"]) else card
        for card in cards
    ]


class FilterModule:
    def filters(self):
        return {"first_seen_merge": first_seen_merge, "with_added": with_added}
