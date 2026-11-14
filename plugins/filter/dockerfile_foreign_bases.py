from __future__ import annotations

from utils.docker.image.toolchain import instructions


def dockerfile_foreign_bases(texts, allowed):
    """Return the images the Dockerfiles start ``FROM`` outside ``allowed``.

    Args:
        texts: the contents of the Dockerfiles a build reads.
        allowed: the base references the build may start from.

    Returns:
        Each offending reference once, in file order. ``scratch`` and the
        stages a file names itself are no image, so they never offend.
    """
    offenders = []
    for text in texts:
        stages = {"scratch"}
        for instruction in instructions(text):
            if instruction.keyword != "FROM":
                continue
            words = [
                word for word in instruction.args.split() if not word.startswith("--")
            ]
            base = words[0]
            foreign = base not in allowed and base.lower() not in stages
            if foreign and base not in offenders:
                offenders.append(base)
            if len(words) == 3 and words[1].upper() == "AS":
                stages.add(words[2].lower())
    return offenders


class FilterModule:
    def filters(self):
        return {"dockerfile_foreign_bases": dockerfile_foreign_bases}
