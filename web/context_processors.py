def api_user(request):
    """Expone el usuario autenticado contra la API en todas las plantillas."""
    return {"api_user": request.session.get("api_user")}
