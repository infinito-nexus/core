from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import MutableMapping, Sequence

T = TypeVar("T")


def buckets(items: Sequence[T], count: int) -> list[tuple[T, ...]]:
    """
    Args:
        items: the inputs one heavy class used to iterate in one process.
        count: the most buckets to split them into.

    Returns:
        ``items`` dealt round-robin into at most ``count`` non-empty tuples;
        every item lands in exactly one, in its original relative order.
    """
    if count < 1:
        raise ValueError(f"bucket count must be positive, got {count}")
    return [bucket for index in range(count) if (bucket := tuple(items[index::count]))]


def register(
    namespace: MutableMapping[str, object],
    name: str,
    base: type,
    **attributes: object,
) -> type[unittest.TestCase]:
    """
    Args:
        namespace: the test module's ``globals()``.
        name: the generated class name; two classes must never share one.
        base: the mixin that carries the tests.
        attributes: the class attributes the mixin reads.

    Returns:
        The generated ``unittest.TestCase``, also bound under ``name`` in
        ``namespace`` so the collector finds it.
    """
    if name in namespace:
        raise AssertionError(f"two generated test classes collapse into {name}")
    generated = type(
        name,
        (base, unittest.TestCase),
        {**attributes, "__module__": namespace["__name__"], "__qualname__": name},
    )
    namespace[name] = generated
    return generated
