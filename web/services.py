"""
Capa de servicios del frontend.

- ApiClient: consume la API FastAPI de timesheets (autenticacion y flujo completo).
- catalog: lectura directa (solo lectura) de los catalogos en Supabase
  (proyectos, centros de costo y usuarios), porque la API no expone
  endpoints de catalogo. Se usa para listas desplegables y para mostrar
  nombres en lugar de UUIDs.
"""

import psycopg
import requests
from django.conf import settings


class ApiError(Exception):
    """Error devuelto por la API (o de conexion con ella)."""

    def __init__(self, mensaje, status_code=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.status_code = status_code


def _extraer_detalle(response):
    """Convierte la respuesta de error de FastAPI en un mensaje legible."""
    try:
        data = response.json()
    except ValueError:
        return f"Error {response.status_code} al comunicar con la API"
    detail = data.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):  # errores de validacion de FastAPI
        partes = []
        for err in detail:
            campo = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query"))
            partes.append(f"{campo}: {err.get('msg')}" if campo else err.get("msg", "Error de validacion"))
        return "; ".join(partes)
    return f"Error {response.status_code} al comunicar con la API"


class ApiClient:
    """Cliente HTTP para la API de timesheets. Usa el token JWT del usuario."""

    def __init__(self, token=None):
        self.base = settings.API_BASE_URL
        self.token = token

    def _headers(self):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, metodo, path, **kwargs):
        url = f"{self.base}{path}"
        kwargs.setdefault("timeout", 30)
        kwargs.setdefault("headers", self._headers())
        try:
            response = requests.request(metodo, url, **kwargs)
        except requests.RequestException as exc:
            raise ApiError(f"No se pudo conectar con la API: {exc}") from exc
        if response.status_code >= 400:
            raise ApiError(_extraer_detalle(response), response.status_code)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # ------------------------------------------------------------
    # Autenticacion
    # ------------------------------------------------------------
    @classmethod
    def login(cls, email, password):
        """Autentica contra la API y devuelve (token, perfil_usuario)."""
        client = cls()
        data = client._request(
            "POST", "/auth/login",
            data={"username": email, "password": password},
        )
        token = data["access_token"]
        client.token = token
        return token, client.me()

    @classmethod
    def registrar(cls, nombre_completo, email, password, rol):
        return cls()._request(
            "POST", "/auth/register",
            json={
                "nombre_completo": nombre_completo,
                "email": email,
                "password": password,
                "rol": rol,
            },
        )

    def me(self):
        return self._request("GET", "/auth/me")

    # ------------------------------------------------------------
    # Timesheets
    # ------------------------------------------------------------
    def listar_timesheets(self, estado=None, proyecto_id=None, periodo=None):
        params = {}
        if estado:
            params["estado"] = estado
        if proyecto_id:
            params["proyecto_id"] = proyecto_id
        if periodo:
            params["periodo"] = periodo
        return self._request("GET", "/timesheets", params=params)

    def obtener_timesheet(self, timesheet_id):
        return self._request("GET", f"/timesheets/{timesheet_id}")

    def crear_timesheet(self, proyecto_id, centro_costo_id, periodo, detalles):
        return self._request(
            "POST", "/timesheets",
            json={
                "proyecto_id": proyecto_id,
                "centro_costo_id": centro_costo_id,
                "periodo": periodo,
                "detalles": detalles,
            },
        )

    def editar_timesheet(self, timesheet_id, detalles):
        return self._request(
            "PUT", f"/timesheets/{timesheet_id}",
            json={"detalles": detalles},
        )

    def enviar_timesheet(self, timesheet_id):
        return self._request("POST", f"/timesheets/{timesheet_id}/enviar")

    def _revisar(self, timesheet_id, accion, comentario=None):
        return self._request(
            "POST", f"/timesheets/{timesheet_id}/{accion}",
            json={"comentario": comentario or None},
        )

    def aprobar(self, timesheet_id, comentario=None):
        return self._revisar(timesheet_id, "aprobar", comentario)

    def rechazar(self, timesheet_id, comentario=None):
        return self._revisar(timesheet_id, "rechazar", comentario)

    def solicitar_correccion(self, timesheet_id, comentario=None):
        return self._revisar(timesheet_id, "solicitar-correccion", comentario)

    def comentar(self, timesheet_id, comentario):
        return self._request(
            "POST", f"/timesheets/{timesheet_id}/comentarios",
            json={"comentario": comentario},
        )


# ------------------------------------------------------------
# Catalogo en Supabase (solo lectura)
# ------------------------------------------------------------

class CatalogoError(Exception):
    pass


def _consultar(sql):
    if not settings.CATALOG_DATABASE_URL:
        raise CatalogoError("No esta configurada la conexion al catalogo (CATALOG_DATABASE_URL)")
    try:
        with psycopg.connect(settings.CATALOG_DATABASE_URL, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                columnas = [desc[0] for desc in cur.description]
                return [dict(zip(columnas, fila)) for fila in cur.fetchall()]
    except psycopg.Error as exc:
        raise CatalogoError(f"No se pudo leer el catalogo: {exc}") from exc


def obtener_proyectos():
    """Proyectos activos con el nombre de su centro de costo."""
    filas = _consultar(
        """
        select p.id, p.codigo, p.nombre, p.centro_costo_id,
               c.codigo as centro_costo_codigo, c.nombre as centro_costo_nombre
        from proyectos p
        left join centros_costo c on c.id = p.centro_costo_id
        where p.activo
        order by p.codigo
        """
    )
    for fila in filas:
        fila["id"] = str(fila["id"])
        fila["centro_costo_id"] = str(fila["centro_costo_id"]) if fila["centro_costo_id"] else ""
    return filas


def obtener_centros_costo():
    filas = _consultar(
        "select id, codigo, nombre from centros_costo where activo order by codigo"
    )
    for fila in filas:
        fila["id"] = str(fila["id"])
    return filas


def obtener_usuarios_map():
    """Mapa id -> {nombre, rol} para mostrar nombres en listas e historial."""
    filas = _consultar("select id, nombre_completo, rol from usuarios")
    return {
        str(fila["id"]): {"nombre": fila["nombre_completo"], "rol": fila["rol"]}
        for fila in filas
    }


def obtener_catalogo():
    """Devuelve (proyectos, centros_costo, mapa_usuarios). Nunca lanza error:
    si el catalogo no esta disponible, devuelve estructuras vacias."""
    try:
        return obtener_proyectos(), obtener_centros_costo(), obtener_usuarios_map()
    except CatalogoError:
        return [], [], {}
