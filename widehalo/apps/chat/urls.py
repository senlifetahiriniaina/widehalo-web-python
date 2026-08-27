from django.urls import path

from apps.chat import views

app_name = "chat"

urlpatterns = [
    path("", views.chat_home, name="home"),
    path("new/", views.chat_new_conversation, name="new_conversation"),
    path("<uuid:channel_id>/", views.chat_home, name="channel"),
    path("<uuid:channel_id>/messages/", views.chat_messages_fragment, name="messages_fragment"),
]
