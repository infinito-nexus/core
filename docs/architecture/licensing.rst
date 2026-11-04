Licence Context
===============

A role's licence and the licence of the software it deploys are two different
questions. This repository's licence governs its own code; the application a
role installs carries its own terms, and that is usually where a restriction
on commercial use actually sits.

The page below answers the second question per role as a matrix of one column
per right, grouped by what the licence permits. Each role names its licence in
``meta/<role>/license.yml``; the rights of a named licence live once in
``meta/licenses.yml``, and the groupings are derived from them. A role that
declares nothing is listed as undetermined rather than left out, so a gap
never reads as permission.

.. toctree::
   :maxdepth: 1

   /generated/licensing
