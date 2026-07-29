from django import template

register = template.Library()

ESTADOS = {
    "borrador": ("Borrador", "secondary"),
    "enviado": ("Enviado", "primary"),
    "aprobado": ("Aprobado", "success"),
    "rechazado": ("Rechazado", "danger"),
    "correccion_solicitada": ("Correccion solicitada", "warning"),
}

EVENTOS = {
    "creado": ("Timesheet creado", "secondary"),
    "editado": ("Timesheet editado", "info"),
    "enviado": ("Enviado a revision", "primary"),
    "aprobado": ("Aprobado", "success"),
    "rechazado": ("Rechazado", "danger"),
    "correccion_solicitada": ("Correccion solicitada", "warning"),
    "comentario": ("Comentario", "light"),
}

ROLES = {
    "consultor": "Consultor",
    "coordinador": "Coordinador",
    "finanzas": "Finanzas",
    "contabilidad": "Contabilidad",
    "presidencia": "Presidencia",
}


@register.filter
def estado_badge(estado):
    """Devuelve la clase de color Bootstrap para un estado."""
    return ESTADOS.get(estado, ("", "secondary"))[1]


@register.filter
def estado_label(estado):
    return ESTADOS.get(estado, (estado, ""))[0]


@register.filter
def evento_badge(evento):
    return EVENTOS.get(evento, ("", "secondary"))[1]


@register.filter
def evento_label(evento):
    return EVENTOS.get(evento, (evento, ""))[0]


@register.filter
def rol_label(rol):
    return ROLES.get(rol, rol)
