from django.contrib import admin
from .models import GameSession, GameType

# Register your models here.
admin.site.register(GameSession)
admin.site.register(GameType)
