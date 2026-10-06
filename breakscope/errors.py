class BreakScopeError(Exception):
    """An error the user can act on. Rendered as message, location and hint."""

    def __init__(
        self,
        message: str,
        *,
        file: str | None = None,
        pointer: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.file = file
        self.pointer = pointer
        self.hint = hint

    def render(self) -> str:
        lines = [f"error: {self.message}"]
        if self.file:
            loc = self.file + (f"#{self.pointer}" if self.pointer else "")
            lines.append(f"  at {loc}")
        if self.hint:
            lines.append(f"  hint: {self.hint}")
        return "\n".join(lines)


class SpecLoadError(BreakScopeError):
    pass


class UnsupportedVersionError(BreakScopeError):
    pass


class RefError(BreakScopeError):
    pass
