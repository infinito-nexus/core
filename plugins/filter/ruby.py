#
# Ansible filter for safely embedding values into Ruby double-quoted strings.
#
# Example:
#   {{ my_password | ruby_dq }}
#
# Output:
#   "escaped_value"
#
# Safe for GitLab Omnibus (gitlab.rb), Chef, Ruby DSLs.


class FilterModule:
    def filters(self):
        return {
            "ruby_dq": self.ruby_double_quoted_string,
            "ruby_single_line": self.ruby_single_line,
        }

    @staticmethod
    def ruby_single_line(value):
        """Collapse a multi-line Ruby program to a single physical line.

        A swarm ``docker stack deploy`` env-file value MUST be one physical
        line; embedded newlines are read as separate (whitespace-named)
        env entries and abort the deploy. Newlines at bracket depth 0 are
        statement boundaries and become ``;``; newlines inside an open
        ``(``/``[``/``{`` (or a quoted string) are continuations and become
        a space, which keeps Ruby hash/array literals valid.

        Args:
            value: Multi-line Ruby source (e.g. GITLAB_OMNIBUS_CONFIG).

        Returns:
            The same program as a single line.
        """
        if value is None:
            return ""

        s = str(value)
        out = []
        depth = 0
        in_str = False
        quote = ""
        i = 0
        n = len(s)
        while i < n:
            c = s[i]
            if in_str:
                if c == "\\" and i + 1 < n:
                    out.append(c)
                    out.append(s[i + 1])
                    i += 2
                    continue
                if c == "\n":
                    # A literal newline inside a string would still corrupt the
                    # single-line env-file; collapse it to a space.
                    out.append(" ")
                    i += 1
                    continue
                out.append(c)
                if c == quote:
                    in_str = False
                i += 1
                continue
            if c in ("'", '"'):
                in_str = True
                quote = c
                out.append(c)
            elif c in "([{":
                depth += 1
                out.append(c)
            elif c in ")]}":
                depth = max(0, depth - 1)
                out.append(c)
            elif c == "\n":
                out.append(";" if depth == 0 else " ")
            else:
                out.append(c)
            i += 1
        return "".join(out)

    @staticmethod
    def ruby_double_quoted_string(value):
        """
        Escape a value for use inside a Ruby double-quoted string
        and wrap it in double quotes.

        Ruby rules handled:
        - "  -> \"
        - \\  -> \\\\
        - newlines -> \n
        - carriage return -> \r
        - tab -> \t

        NOT escaped on purpose:
        - $
        - €
        - !
        - '
        """

        if value is None:
            return '""'

        s = str(value)

        # Escape backslash first
        s = s.replace("\\", "\\\\")

        # Escape double quotes
        s = s.replace('"', '\\"')

        # Escape control characters
        s = s.replace("\n", "\\n")
        s = s.replace("\r", "\\r")
        s = s.replace("\t", "\\t")

        return f'"{s}"'
