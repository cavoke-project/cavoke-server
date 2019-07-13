from datetime import datetime
import uuid

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class GameSession(models.Model):
    game_session_id = models.CharField(max_length=100)

    player_uid = models.CharField(max_length=100)
    game_type_id = models.CharField(max_length=100)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created', 'player_uid', 'game_type_id', 'game_session_id')

    def __str__(self):
        return self.game_session_id

    def save(self, *args, **kwargs):
        if not self.game_session_id:
            self.created = datetime.now()
            self.game_session_id = uuid.uuid4().__str__()
        return super(GameSession, self).save(*args, **kwargs)


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField(max_length=500, blank=True)
    location = models.CharField(max_length=30, blank=True)
    birth_date = models.DateField(null=True, blank=True)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()
