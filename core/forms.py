"""Aides de formulaires réutilisables entre apps."""
from django import forms


class BootstrapFormMixin:
    """Ajoute les classes Bootstrap aux champs, sans dupliquer le style par template."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = (existing + " form-check-input").strip()
            else:
                field.widget.attrs["class"] = (existing + " form-control").strip()
