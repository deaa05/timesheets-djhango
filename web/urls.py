from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.lista_view, name="lista"),
    path("login/", views.login_view, name="login"),
    path("registro/", views.registro_view, name="registro"),
    path("logout/", views.logout_view, name="logout"),
    path("timesheets/nuevo/", views.crear_view, name="crear"),
    path("timesheets/<uuid:timesheet_id>/", views.detalle_view, name="detalle"),
    path("timesheets/<uuid:timesheet_id>/editar/", views.editar_view, name="editar"),
    path("timesheets/<uuid:timesheet_id>/enviar/", views.enviar_view, name="enviar"),
    path("timesheets/<uuid:timesheet_id>/revisar/", views.revisar_view, name="revisar"),
    path("timesheets/<uuid:timesheet_id>/comentar/", views.comentar_view, name="comentar"),
]
