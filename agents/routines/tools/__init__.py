"""Shared deterministic tool nodes for the routines: pure functions that parse a
log, a diff or a text and return a verdict, with no model call and no live I/O.
A routine graph wraps one of these into a node that reads the tool's inputs from
the run state and writes its result back; the pure function is what a unit test
exercises on a recorded fixture.
"""
