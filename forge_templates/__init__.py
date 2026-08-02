"""Compile-time textual template expansion for Forge source files."""

from .expander import TemplateExpansionError, expand_template_sources, expand_templates

__all__ = ["TemplateExpansionError", "expand_template_sources", "expand_templates"]
