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

"""
Time delta, that game sessions should be valid for
"""
GAMESESSION_VALID_FOR = timezone.timedelta(weeks=1)

"""
Maximum number of games each user can author
"""
MAX_GAMES_FOR_USER = 10

# url validator
validator = URLValidator()

logger = logging.getLogger(__name__)


def git(*args):
    """
    function to use git
    :param args: git params
    """
    return subprocess.check_call(['git'] + list(args))


class GameSession(models.Model):
    """
    GameSession model
    """
    # id of game session
    game_session_id = models.CharField(max_length=100, unique=True)

    # uid of player
    player_uid = models.CharField(max_length=100)

    # game type of game session
    game_type = models.ForeignKey(
        'GameType',
        on_delete=models.CASCADE,
        null=True
    )

    # timestamp of time when created
    createdOn = models.DateTimeField(auto_now_add=True)

    # game session expiration stamp
    expiresOn = models.DateTimeField()

    class Meta:
        ordering = ('createdOn', 'player_uid', 'game_type_id', 'game_session_id', 'expiresOn')

    def __str__(self):
        return self.game_session_id

    def save(self, *args, **kwargs):
        if not self.game_session_id:
            # called on create, so we initialize
            self.createdOn = timezone.now()
            self.expiresOn = self.createdOn + GAMESESSION_VALID_FOR
            self.game_session_id = uuid.uuid4().__str__()

            self.__createGameObject()

        return super(GameSession, self).save(*args, **kwargs)

    def __createGameObject(self):
        """
        create Game object from cavoke-lib
        """
        gt_id = self.game_type.game_type_id
        if gt_id in game_type_dict:
            module = game_type_dict[gt_id]
        else:
            raise ValueError("Game type doesn't exist")
        session = module.MyGame()
        game_session_dict[self.game_session_id] = (session, Lock())


class Profile(models.Model):
    """
    Additional OneToOneField for main django user model for easier firebase interaction
    """
    # main Django user model
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # games authored integer
    gamesMadeCount = models.IntegerField(default=0)
    # maximum amount of games allowed to made
    gamesMadeMaxCount = models.IntegerField(default=MAX_GAMES_FOR_USER)

    # first api request timestamp
    firstActionOn = models.DateTimeField(default=timezone.now)
    # timestamp of last game session use
    lastPlayedOn = models.DateTimeField(default=timezone.now)
    # timestamp of last authoring
    lastGameCreatedOn = models.DateTimeField(default=timezone.now)

    def update_lastPlayedOn(self):
        self.lastPlayedOn = timezone.now()

    def update_lastGameCreatedOn(self):
        self.lastGameCreatedOn = timezone.now()

    def uid(self) -> str:
        """
        gets id for profile
        :return: id as str
        """
        return FirebaseUser.objects.get(user=self.user).uid
    # TODO find out if we even need this
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


class GameType(models.Model):
    """
    Model for game type
    """
    # id of game type
    game_type_id = models.CharField(max_length=100, null=False)

    # game type name
    name = models.CharField(max_length=100, null=False)
    # game type's creator
    creator = models.CharField(max_length=100, null=False)
    # game type's creator name
    creator_display_name = models.CharField(max_length=100, null=False)
    # git url for game type
    git_url = models.CharField(max_length=100, null=False)
    # description for game type
    description = models.CharField(max_length=1000, default='No description')

    # times the game was played TODO implement
    timesPlayed = models.IntegerField(default=0)
    # timestamp of creation time
    createdOn = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.createdOn:
            # called on create
            self.createdOn = timezone.now()

            # downloads creator's game code
            gt_id = self.game_type_id
            gitUrl = self.git_url
            # check if valid url
            try:
                validator(gitUrl)
                if gitUrl[-4:] != '.git':
                    raise ValidationError
            except ValidationError:
                raise ValueError("provided url is invalid")
            # try cloning
            try:
                logger.info("Cloning {" + gt_id + "}...")
                git('clone', gitUrl, './cavoke_app/game_modules/' + gt_id)
            except Exception as e:
                logger.error("Cloning of {" + gt_id + "} failed! Details: {" + str(e) + "}")
                raise RuntimeError(str(e))
            else:
                logger.info("Cloning of {" + gt_id + "} is complete!")

            # TODO make it work with src/setup.py stuff
            # save
            module = import_module('cavoke_app.game_modules.' + gt_id)
            game_type_dict[gt_id] = module
        return super(GameType, self).save(*args, **kwargs)
