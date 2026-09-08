"""Runtime coordination layer that connects milestone services without owning their internals."""

from .service import RuntimeCoordinator, RuntimeCoordinatorError

__all__ = ["RuntimeCoordinator", "RuntimeCoordinatorError"]
