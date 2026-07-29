import functools

from django.shortcuts import redirect


def api_login_required(vista):
    """Exige que exista un token de la API en la sesion; si no, redirige al login."""

    @functools.wraps(vista)
    def wrapper(request, *args, **kwargs):
        if not request.session.get("api_token"):
            return redirect("web:login")
        return vista(request, *args, **kwargs)

    return wrapper


def rol_requerido(*roles):
    """Exige que el usuario de la API tenga uno de los roles indicados."""

    def decorador(vista):
        @functools.wraps(vista)
        @api_login_required
        def wrapper(request, *args, **kwargs):
            usuario = request.session.get("api_user") or {}
            if usuario.get("rol") not in roles:
                from django.contrib import messages

                messages.error(request, "No tienes permisos para realizar esta accion.")
                return redirect("web:lista")
            return vista(request, *args, **kwargs)

        return wrapper

    return decorador
