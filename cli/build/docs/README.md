# Documentation Generators 📝

Generators that render pages committed under `docs/`. Each one reads role metadata, renders a single page, and writes it back into the documentation tree, so `docs/` holds only the rendered result and never the code that produces it. A lint fails when a generated page drifts from a fresh run, so every page here is regenerated through its own make target rather than edited by hand.
