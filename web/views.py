from datetime import date

from django.contrib import messages
from django.shortcuts import redirect, render

from .decorators import api_login_required, rol_requerido
from .services import ApiClient, ApiError, obtener_catalogo

ROLES = [
    ("consultor", "Consultor"),
    ("coordinador", "Coordinador"),
    ("finanzas", "Finanzas"),
    ("contabilidad", "Contabilidad"),
    ("presidencia", "Presidencia"),
]

ESTADOS = [
    ("borrador", "Borrador"),
    ("enviado", "Enviado"),
    ("aprobado", "Aprobado"),
    ("rechazado", "Rechazado"),
    ("correccion_solicitada", "Correccion solicitada"),
]


# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------

def _client(request):
    return ApiClient(token=request.session.get("api_token"))


def _cerrar_sesion_si_401(request, error):
    """Si el token vencio o es invalido, limpia la sesion y pide login de nuevo."""
    if error.status_code == 401:
        request.session.flush()
        messages.warning(request, "Tu sesion expiro. Inicia sesion nuevamente.")
        return True
    return False


def _enriquecer(timesheets, proyectos, usuarios_map):
    """Agrega nombres legibles (proyecto, consultor, centro de costo) a cada timesheet."""
    proyectos_map = {p["id"]: p for p in proyectos}
    for ts in timesheets:
        proyecto = proyectos_map.get(ts["proyecto_id"], {})
        ts["nombre_proyecto"] = proyecto.get("nombre", ts["proyecto_id"][:8])
        ts["codigo_proyecto"] = proyecto.get("codigo", "")
        ts["nombre_centro_costo"] = proyecto.get("centro_costo_nombre", "")
        consultor = usuarios_map.get(ts["consultor_id"], {})
        ts["nombre_consultor"] = consultor.get("nombre", ts["consultor_id"][:8])
    return timesheets


def _parse_detalles(post):
    """Lee las filas dinamicas del formulario y devuelve (detalles, errores)."""
    fechas = post.getlist("detalle_fecha")
    actividades = post.getlist("detalle_actividad")
    horas_lista = post.getlist("detalle_horas")

    detalles, errores = [], []
    for i, (fecha, actividad, horas) in enumerate(zip(fechas, actividades, horas_lista), start=1):
        if not fecha and not actividad.strip() and not horas.strip():
            continue  # fila vacia
        if not fecha:
            errores.append(f"Fila {i}: falta la fecha.")
            continue
        try:
            date.fromisoformat(fecha)
        except ValueError:
            errores.append(f"Fila {i}: la fecha '{fecha}' no es valida.")
            continue
        if not actividad.strip():
            errores.append(f"Fila {i}: falta la descripcion de la actividad.")
            continue
        try:
            valor_horas = float(horas)
            if not (0 < valor_horas <= 24):
                raise ValueError
        except (TypeError, ValueError):
            errores.append(f"Fila {i}: las horas deben ser un numero mayor que 0 y hasta 24.")
            continue
        detalles.append({"fecha": fecha, "actividad": actividad.strip(), "horas": valor_horas})
    return detalles, errores


# ------------------------------------------------------------
# Autenticacion
# ------------------------------------------------------------

def login_view(request):
    if request.session.get("api_token"):
        return redirect("web:lista")

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        try:
            token, usuario = ApiClient.login(email, password)
        except ApiError as e:
            messages.error(request, e.mensaje)
        else:
            request.session["api_token"] = token
            request.session["api_user"] = usuario
            messages.success(request, f"Bienvenido/a {usuario['nombre_completo']}.")
            return redirect("web:lista")

    return render(request, "web/login.html")


def registro_view(request):
    if request.method == "POST":
        nombre = request.POST.get("nombre_completo", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        rol = request.POST.get("rol", "consultor")

        if password != password2:
            messages.error(request, "Las contrasenas no coinciden.")
        elif rol not in dict(ROLES):
            messages.error(request, "Rol no valido.")
        else:
            try:
                ApiClient.registrar(nombre, email, password, rol)
            except ApiError as e:
                messages.error(request, e.mensaje)
            else:
                messages.success(request, "Cuenta creada correctamente. Ya puedes iniciar sesion.")
                return redirect("web:login")

    return render(request, "web/registro.html", {"roles": ROLES})


def logout_view(request):
    request.session.flush()
    messages.info(request, "Sesion cerrada.")
    return redirect("web:login")


# ------------------------------------------------------------
# Listado con filtros (RF-10)
# ------------------------------------------------------------

@api_login_required
def lista_view(request):
    estado = request.GET.get("estado") or None
    proyecto_id = request.GET.get("proyecto_id") or None
    periodo = request.GET.get("periodo") or None

    proyectos, _, usuarios_map = obtener_catalogo()
    timesheets = []
    try:
        timesheets = _client(request).listar_timesheets(
            estado=estado, proyecto_id=proyecto_id, periodo=periodo
        )
        _enriquecer(timesheets, proyectos, usuarios_map)
    except ApiError as e:
        if _cerrar_sesion_si_401(request, e):
            return redirect("web:login")
        messages.error(request, e.mensaje)

    contexto = {
        "timesheets": timesheets,
        "estados": ESTADOS,
        "proyectos": proyectos,
        "filtro_estado": estado or "",
        "filtro_proyecto": proyecto_id or "",
        "filtro_periodo": periodo or "",
    }
    return render(request, "web/lista.html", contexto)


# ------------------------------------------------------------
# Crear timesheet (RF-01, RF-02)
# ------------------------------------------------------------

@rol_requerido("consultor")
def crear_view(request):
    proyectos, centros_costo, _ = obtener_catalogo()

    if request.method == "POST":
        proyecto_id = request.POST.get("proyecto_id", "")
        centro_costo_id = request.POST.get("centro_costo_id", "")
        periodo = request.POST.get("periodo", "")
        detalles, errores = _parse_detalles(request.POST)

        # Si el proyecto define su centro de costo, se usa ese (RF-09)
        proyecto = next((p for p in proyectos if p["id"] == proyecto_id), None)
        if proyecto and proyecto.get("centro_costo_id"):
            centro_costo_id = proyecto["centro_costo_id"]

        if not proyecto_id:
            errores.append("Selecciona un proyecto.")
        if not centro_costo_id:
            errores.append("Selecciona un centro de costo.")
        if not periodo:
            errores.append("Selecciona el periodo (mes).")

        if errores:
            for err in errores:
                messages.error(request, err)
        else:
            try:
                ts = _client(request).crear_timesheet(
                    proyecto_id, centro_costo_id, periodo, detalles
                )
            except ApiError as e:
                if _cerrar_sesion_si_401(request, e):
                    return redirect("web:login")
                messages.error(request, e.mensaje)
            else:
                messages.success(
                    request,
                    "Timesheet guardado como borrador. Puedes editarlo y enviarlo cuando este listo.",
                )
                return redirect("web:detalle", timesheet_id=ts["id"])

    return render(
        request,
        "web/form.html",
        {
            "modo": "crear",
            "proyectos": proyectos,
            "centros_costo": centros_costo,
            "periodo_default": date.today().strftime("%Y-%m"),
        },
    )


# ------------------------------------------------------------
# Editar borrador / correccion (RF-02, RF-11)
# ------------------------------------------------------------

@rol_requerido("consultor")
def editar_view(request, timesheet_id):
    proyectos, _, _ = obtener_catalogo()
    try:
        ts = _client(request).obtener_timesheet(timesheet_id)
    except ApiError as e:
        if _cerrar_sesion_si_401(request, e):
            return redirect("web:login")
        messages.error(request, e.mensaje)
        return redirect("web:lista")

    if request.method == "POST":
        detalles, errores = _parse_detalles(request.POST)
        if errores:
            for err in errores:
                messages.error(request, err)
        else:
            try:
                _client(request).editar_timesheet(timesheet_id, detalles)
            except ApiError as e:
                if _cerrar_sesion_si_401(request, e):
                    return redirect("web:login")
                messages.error(request, e.mensaje)
            else:
                messages.success(request, "Timesheet actualizado (se registro una nueva version).")
                return redirect("web:detalle", timesheet_id=timesheet_id)

    proyecto = next((p for p in proyectos if p["id"] == ts["proyecto_id"]), {})
    return render(
        request,
        "web/form.html",
        {
            "modo": "editar",
            "ts": ts,
            "nombre_proyecto": proyecto.get("nombre", ts["proyecto_id"]),
            "nombre_centro_costo": proyecto.get("centro_costo_nombre", ""),
        },
    )


# ------------------------------------------------------------
# Detalle: detalles, historial, acciones del flujo (RF-04, RF-05, RF-12)
# ------------------------------------------------------------

@api_login_required
def detalle_view(request, timesheet_id):
    proyectos, _, usuarios_map = obtener_catalogo()
    try:
        ts = _client(request).obtener_timesheet(timesheet_id)
    except ApiError as e:
        if _cerrar_sesion_si_401(request, e):
            return redirect("web:login")
        messages.error(request, e.mensaje)
        return redirect("web:lista")

    _enriquecer([ts], proyectos, usuarios_map)
    for evento in ts.get("historial", []):
        usuario = usuarios_map.get(evento["usuario_id"], {})
        evento["nombre_usuario"] = usuario.get("nombre", evento["usuario_id"][:8])

    usuario = request.session.get("api_user") or {}
    es_dueno = ts["consultor_id"] == usuario.get("id")
    contexto = {
        "ts": ts,
        "puede_editar": es_dueno and ts["estado"] in ("borrador", "correccion_solicitada"),
        "puede_enviar": es_dueno and ts["estado"] in ("borrador", "correccion_solicitada"),
        "puede_revisar": usuario.get("rol") == "coordinador" and ts["estado"] == "enviado",
        "nombre_revisor": usuarios_map.get(ts.get("revisado_por") or "", {}).get("nombre", ""),
    }
    return render(request, "web/detalle.html", contexto)


# ------------------------------------------------------------
# Acciones del flujo de aprobacion
# ------------------------------------------------------------

@rol_requerido("consultor")
def enviar_view(request, timesheet_id):
    if request.method == "POST":
        try:
            _client(request).enviar_timesheet(timesheet_id)
        except ApiError as e:
            if _cerrar_sesion_si_401(request, e):
                return redirect("web:login")
            messages.error(request, e.mensaje)
        else:
            messages.success(
                request,
                "Timesheet enviado. Se notifico al coordinador del proyecto (RF-03).",
            )
    return redirect("web:detalle", timesheet_id=timesheet_id)


@rol_requerido("coordinador")
def revisar_view(request, timesheet_id):
    """Aprobar, rechazar o solicitar correccion (RF-04) con comentario (RF-12)."""
    if request.method == "POST":
        accion = request.POST.get("accion", "")
        comentario = request.POST.get("comentario", "").strip()
        cliente = _client(request)
        try:
            if accion == "aprobar":
                cliente.aprobar(timesheet_id, comentario)
                messages.success(request, "Timesheet aprobado.")
            elif accion == "rechazar":
                cliente.rechazar(timesheet_id, comentario)
                messages.success(request, "Timesheet rechazado.")
            elif accion == "solicitar-correccion":
                if not comentario:
                    raise ApiError("Indica las correcciones necesarias en el comentario.")
                cliente.solicitar_correccion(timesheet_id, comentario)
                messages.success(request, "Se solicitaron correcciones al consultor.")
            else:
                raise ApiError("Accion no valida.")
        except ApiError as e:
            if _cerrar_sesion_si_401(request, e):
                return redirect("web:login")
            messages.error(request, e.mensaje)
    return redirect("web:detalle", timesheet_id=timesheet_id)


@api_login_required
def comentar_view(request, timesheet_id):
    if request.method == "POST":
        comentario = request.POST.get("comentario", "").strip()
        try:
            if not comentario:
                raise ApiError("El comentario no puede estar vacio.")
            _client(request).comentar(timesheet_id, comentario)
        except ApiError as e:
            if _cerrar_sesion_si_401(request, e):
                return redirect("web:login")
            messages.error(request, e.mensaje)
        else:
            messages.success(request, "Comentario agregado al historial.")
    return redirect("web:detalle", timesheet_id=timesheet_id)
