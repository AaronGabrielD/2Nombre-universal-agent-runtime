"""Tool and capability registry primitives."""

from .models import CapabilitySpec, ToolRegistration
from .registry import RegistryError, ToolCapabilityRegistry

__all__ = ["CapabilitySpec", "RegistryError", "ToolCapabilityRegistry", "ToolRegistration"]
