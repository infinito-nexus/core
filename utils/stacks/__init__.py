"""Which local stacks a make target starts, from ``compose/stacks.yml``.

The declaration names, per stack, its lifecycle class, the stacks it runs
against and the targets whose own recipe reaches it. A target that only calls
other targets, as a prerequisite, through ``$(MAKE)`` or through
``scripts/make/parallel.sh``, inherits their stacks, so an aggregate such as
``quality-high`` is never declared twice.
"""
