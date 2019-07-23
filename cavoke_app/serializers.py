import logging
import subprocess
import uuid
from importlib import import_module

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from drf_firebase_auth_cavoke.models import FirebaseUser
from rest_framework.serializers import ModelSerializer

from cavoke_app.models import GameSession, GameType


class GameSessionSerializer(ModelSerializer):
    class Meta:
        model = GameSession
        fields = '__all__'

    def createInstance(self):
        return GameSession(**self.validated_data)


class GameTypeSerializer(ModelSerializer):
    class Meta:
        model = GameType
        fields = '__all__'

    def createInstance(self):
        return GameType(**self.validated_data)
