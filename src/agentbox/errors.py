class AgentboxError(Exception):
    """An expected failure safe to show without a traceback."""

    def __init__(self, message, *, code="operation_failed", details=None):
        super().__init__(message)
        self.code = code
        self.details = details
