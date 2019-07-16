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

from .gamestorage import *

GAMESESSION_VALID_FOR = timezone.timedelta(weeks=1)
MAX_GAMES_FOR_USER = 10

validator = URLValidator()

from cavoke_server import db

logger = logging.getLogger(__name__)


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

            try:
                logger.info("Cloning {" + gt_id + "}...")
                git('clone', gitUrl, './cavoke_app/game_modules/' + gt_id)
            except Exception as e:
                logger.error("Cloning of {" + gt_id + "} failed! Details: {" + str(e) + "}")
                raise RuntimeError(str(e))
            else:
                logger.info("Cloning of {" + gt_id + "} is complete!")

            # TODO make it work with src/setup.py stuff
            module = import_module('cavoke_app.game_modules.' + self.game_type_id)

            game_type_dict[self.game_type_id] = module
        session = module.MyGame()
        game_session_dict[self.game_session_id] = (session, Lock())


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    gamesMadeCount = models.IntegerField(default=0)
    gamesMadeMaxCount = models.IntegerField(default=MAX_GAMES_FOR_USER)

    firstActionOn = models.DateTimeField(default=timezone.now)
    lastPlayedOn = models.DateTimeField(default=timezone.now)
    lastGameCreatedOn = models.DateTimeField(default=timezone.now)

    def update_lastPlayedOn(self):
        self.lastPlayedOn = timezone.now()

    def update_lastGameCreatedOn(self):
        self.lastGameCreatedOn = timezone.now()

    def uid(self):
        return FirebaseUser.objects.get(user=self.user).uid
    #
    # def addAuthoredGame(self, gameId: str):
    #     # TODO make atomic
    #     gdoc = db.collection('users').document(self.uid()).get()
    #     gdict: dict = gdoc.to_dict()
    #     gdict['authored_games'].append(gameId)
    #     db.collection('users').document(self.uid()).set(gdict)
    #
    # def authoredGames(self) -> List[str]:
    #     return db.collection('users').document(self.uid()).get().to_dict()['authored_games']


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()
