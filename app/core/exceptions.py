"""Domain-specific exceptions for the runtime."""


class RuntimeErrorBase(Exception):
    """Base exception for expected runtime failures."""


class RuntimeConfigurationError(RuntimeErrorBase):
    """Raised when configuration is invalid or incomplete."""


class ContractValidationError(RuntimeErrorBase):
    """Raised when an input violates a runtime contract."""


class IllegalStateTransition(RuntimeErrorBase):
    """Raised when a workflow attempts an unsupported state transition."""
