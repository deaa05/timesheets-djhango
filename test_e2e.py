"""Prueba end-to-end del frontend Django contra la API real (no forma parte del proyecto)."""
import os
import re
import sys
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings

settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]

from django.test import Client

from web.services import obtener_proyectos

CONSULTOR = {"email": "consultor.prueba@corpei.com", "password": "prueba1234"}
COORDINADOR = {"email": "coordinador.prueba@corpei.com", "password": "prueba1234"}

fallos = []


def check(nombre, condicion, extra=""):
    estado = "OK " if condicion else "FALLO"
    print(f"[{estado}] {nombre} {extra}")
    if not condicion:
        fallos.append(nombre)


def login(client, creds):
    r = client.post("/login/", {"email": creds["email"], "password": creds["password"]})
    return r


def main():
    proyectos = obtener_proyectos()
    proyecto = next(p for p in proyectos if p["centro_costo_id"])
    print("Proyecto de prueba:", proyecto["codigo"], proyecto["nombre"])
    periodo = "2026-" + uuid.uuid4().hex[:2].replace("0", "1")  # periodo unico por corrida... no, mes valido
    periodo = "2026-" + str((uuid.uuid4().int % 12) + 1).zfill(2)

    # ---------- CONSULTOR ----------
    c = Client()

    r = c.get("/")
    check("raiz redirige a login sin sesion", r.status_code == 302 and "/login" in r.url)

    r = c.get("/login/")
    check("pagina login carga", r.status_code == 200)

    r = login(c, CONSULTOR)
    check("login consultor redirige a lista", r.status_code == 302 and r.url == "/")
    check("sesion guarda usuario", c.session.get("api_user", {}).get("rol") == "consultor")

    r = c.get("/")
    check("lista carga logueado", r.status_code == 200)
    check("lista muestra tabla", b"Timesheets" in r.content)

    r = c.get("/", {"estado": "borrador", "periodo": "2026-07"})
    check("filtros funcionan", r.status_code == 200)

    r = c.get("/timesheets/nuevo/")
    check("formulario crear carga", r.status_code == 200)
    check("formulario lista proyectos", proyecto["nombre"].encode() in r.content)

    detalles = {
        "proyecto_id": proyecto["id"],
        "centro_costo_id": proyecto["centro_costo_id"],
        "periodo": periodo,
        "detalle_fecha": [f"{periodo}-05", f"{periodo}-06"],
        "detalle_actividad": ["Reunion de planificacion", "Desarrollo de informe"],
        "detalle_horas": ["4", "6.5"],
    }
    r = c.post("/timesheets/nuevo/", detalles)
    if r.status_code == 409 or (r.status_code == 200 and b"Ya existe" in r.content):
        print("   (periodo ya usado, reintentando con otro)")
        periodo = "2026-" + str((uuid.uuid4().int % 12) + 1).zfill(2)
        detalles["periodo"] = periodo
        detalles["detalle_fecha"] = [f"{periodo}-05", f"{periodo}-06"]
        r = c.post("/timesheets/nuevo/", detalles)
    check("crear timesheet redirige al detalle", r.status_code == 302 and "/timesheets/" in r.url)
    ts_id = r.url.rstrip("/").split("/")[-1]
    print("   timesheet creado:", ts_id, "periodo:", periodo)

    r = c.get(f"/timesheets/{ts_id}/")
    check("detalle carga", r.status_code == 200)
    check("detalle muestra estado borrador", b"Borrador" in r.content)
    check("detalle muestra actividades", "Desarrollo de informe".encode() in r.content)
    check("detalle muestra boton enviar", b"Enviar a revision" in r.content)

    # Editar borrador (RF-02)
    r = c.post(f"/timesheets/{ts_id}/editar/", {
        "detalle_fecha": [f"{periodo}-07"],
        "detalle_actividad": ["Actividad corregida"],
        "detalle_horas": ["8"],
    })
    check("editar borrador redirige", r.status_code == 302)
    r = c.get(f"/timesheets/{ts_id}/")
    check("edicion guardada (v2)", b"Actividad corregida" in r.content and b"version 2" in r.content)

    # Comentario (RF-12)
    r = c.post(f"/timesheets/{ts_id}/comentar/", {"comentario": "Comentario del consultor"})
    check("comentario consultor", r.status_code == 302)

    # Enviar (RF-03)
    r = c.post(f"/timesheets/{ts_id}/enviar/")
    check("enviar redirige", r.status_code == 302)
    r = c.get(f"/timesheets/{ts_id}/")
    check("estado enviado", b"Enviado" in r.content)
    check("ya no se puede editar tras envio", b"Editar horas" not in r.content)

    # ---------- COORDINADOR ----------
    k = Client()
    r = login(k, COORDINADOR)
    check("login coordinador", r.status_code == 302)

    r = k.get(f"/timesheets/{ts_id}/")
    check("coordinador ve detalle", r.status_code == 200)
    check("coordinador ve panel de revision", b"Revision del coordinador" in r.content)
    check("historial incluye comentario", "Comentario del consultor".encode() in r.content)

    # Solicitar correccion (RF-04)
    r = k.post(f"/timesheets/{ts_id}/revisar/", {
        "accion": "solicitar-correccion",
        "comentario": "Falta detalle en las actividades del dia 7",
    })
    check("solicitar correccion", r.status_code == 302)

    # Consultor corrige y reenvia
    r = c.get(f"/timesheets/{ts_id}/")
    check("consultor ve correccion solicitada", "Correccion solicitada".encode() in r.content)
    check("puede editar tras correccion", b"Editar horas" in r.content)
    c.post(f"/timesheets/{ts_id}/editar/", {
        "detalle_fecha": [f"{periodo}-07", f"{periodo}-08"],
        "detalle_actividad": ["Actividad corregida con detalle", "Documentacion tecnica"],
        "detalle_horas": ["8", "4"],
    })
    c.post(f"/timesheets/{ts_id}/enviar/")

    # Coordinador aprueba (RF-04)
    r = k.post(f"/timesheets/{ts_id}/revisar/", {"accion": "aprobar", "comentario": "Aprobado, gracias"})
    check("aprobar", r.status_code == 302)
    r = k.get(f"/timesheets/{ts_id}/")
    check("estado aprobado", b"Aprobado" in r.content)
    check("historial muestra aprobacion", "Aprobado, gracias".encode() in r.content)

    # Lista del coordinador ve el timesheet aprobado con filtro
    r = k.get("/", {"estado": "aprobado"})
    check("filtro aprobados lista el timesheet", proyecto["nombre"].encode() in r.content)

    # ---------- PERMISOS ----------
    r = k.get("/timesheets/nuevo/")
    check("coordinador no puede crear (redirige)", r.status_code == 302)

    r = Client().get(f"/timesheets/{ts_id}/")
    check("anonimo redirige a login", r.status_code == 302)

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} pruebas fallaron:", fallos)
        sys.exit(1)
    print("RESULTADO: todas las pruebas pasaron")


if __name__ == "__main__":
    main()
