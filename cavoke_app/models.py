import os
import uuid
import subprocess
from importlib import import_module
import logging

from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

from cavoke_server.settings import BASE_DIR
from .gamestorage import *

GAMESESSION_VALID_FOR = timezone.timedelta(weeks=1)

validator = URLValidator()

try:
    cred = credentials.Certificate(os.path.join(BASE_DIR, 'cavoke_server',
                                                'cavoke-firebase-firebase-adminsdk-tvoxx-ba98bbb529.json'))
    firebase_admin.initialize_app(cred)
except ValueError:
    pass
db = firestore.client()


def git(*args):
    return subprocess.check_call(['git'] + list(args))


class GameSession(models.Model):
    game_session_id = models.CharField(max_length=100, unique=True)

    player_uid = models.CharField(max_length=100)
    game_type_id = models.CharField(max_length=100)
    createdOn = models.DateTimeField(auto_now_add=True)
    expiresOn = models.DateTimeField()

    class Meta:
        ordering = ('createdOn', 'player_uid', 'game_type_id', 'game_session_id', 'expiresOn')

    def __str__(self):
        return self.game_session_id

    def save(self, *args, **kwargs):
        if not self.game_session_id:
            # called on create
            self.createdOn = timezone.now()
            self.expiresOn = self.createdOn + GAMESESSION_VALID_FOR
            self.game_session_id = uuid.uuid4().__str__()

            self.__createGameObject()

        return super(GameSession, self).save(*args, **kwargs)

    def __createGameObject(self):
        gt_id = self.game_type_id
        if gt_id in game_type_dict:
            module = game_type_dict[gt_id]
        else:
            gdoc = db.collection('games').document(gt_id).get()
            if not gdoc._exists:
                raise ValueError("invalid game_type_id")
            gdict: dict = gdoc.to_dict()
            gitUrl = gdict['git_url']
            try:
                validator(gitUrl)
                if gitUrl[-4:] != '.git':
                    raise ValidationError
            except ValidationError:
                raise ValueError("provided url is invalid")

            logging.info("Cloning {" + gt_id + "}...")
            try:
                git('clone', gitUrl, './cavoke_app/game_modules/' + gt_id)
            except:
                logging.error("Cloning of {" + gt_id + "} failed!")
            else:
                logging.info("Cloning of {" + gt_id + "} is complete!")

            # TODO make it work
            module = import_module(self.game_type_id)
            game_type_dict[self.game_type_id] = module
        session = module.MyGame()
        game_session_dict[self.game_session_id] = (session, Lock())


class Profile(models.Model):
    # make it work
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
