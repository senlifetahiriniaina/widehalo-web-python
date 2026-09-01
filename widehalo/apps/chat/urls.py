from django.urls import path

from apps.chat import views

app_name = "chat"

urlpatterns = [
    path("", views.chat_home, name="home"),
    path("new/", views.chat_new_conversation, name="new_conversation"),
    path("launcher/", views.chat_launcher, name="launcher"),
    path("launcher/users/", views.chat_launcher_users, name="launcher_users"),
    path("launcher/start/", views.chat_launcher_start, name="launcher_start"),
    path("<uuid:channel_id>/", views.chat_home, name="channel"),
    path("<uuid:channel_id>/messages/", views.chat_messages_fragment, name="messages_fragment"),
]
