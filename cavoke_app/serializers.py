import uuid
from rest_framework import serializers

from .models import GameSession


class GameSerializer(serializers.Serializer):
    player_uid = serializers.CharField(max_length=100)
    game_session_id = serializers.CharField(max_length=100)
    game_type_id = serializers.CharField(max_length=100)
    created = serializers.DateTimeField()
    # is called if we save serializer if it do not have an instance

    def create(self, validated_data):
        gameSession = GameSession.objects.create(**validated_data)
        gameSession.game_session_id = uuid.uuid4().__str__()
        gameSession.save()
        return gameSession

    # is called if we save serializer if it have an instance
    def update(self, instance, validated_data):
        instance.__dict__.update(validated_data)
        instance.save()
        return instance
