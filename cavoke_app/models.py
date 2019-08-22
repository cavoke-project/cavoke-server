import logging
import os
import subprocess
import pickle
from pickle import HIGHEST_PROTOCOL
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
from .exceptions import *
from .config import *

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

    # object of game in binary to be decoded with pickle
    game_object_bytes = models.BinaryField()

    class Meta:
        ordering = ('createdOn', 'player_uid', 'game_type_id', 'game_session_id', 'expiresOn')

    def __str__(self):
        return self.game_session_id

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__game = None

    def save(self, *args, **kwargs):
        if not self.game_session_id:
            # check if session count is ok
            if GameSession.objects.filter(player_uid=self.player_uid).count() > MAX_ACTIVE_GAME_SESSIONS:
                raise TooManyGameSessionsWarning

            # called on create, so we initialize
            self.createdOn = timezone.now()
            self.expiresOn = self.createdOn + GAMESESSION_VALID_FOR
            self.game_session_id = randomUUID()

            self.__createGameObject()

        return super(GameSession, self).save(*args, **kwargs)

    def __createGameObject(self):
        """
        create Game object from cavoke-lib
        """
        gt_id = self.game_type.game_type_id
        gt = GameType.objects.get(game_type_id=gt_id)
        module = gt.getGameModule()
        session = module.MyGame()
        self.__game = session
        self.game_object_bytes = pickle.dumps(session, HIGHEST_PROTOCOL)

    def getCavokeGame(self) -> Game:
        """
        Read game binary and make it into a game object
        :return: cavoke game
        """
        if self.__game is not None:
            return self.__game
        game = pickle.loads(self.game_object_bytes)
        self.__game = game
        return game


class Profile(models.Model):
    """
    Additional OneToOneField for main django user model for easier firebase interaction
    """
    # main Django user model
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # TODO remove this "Костыль"-like code
    # games authored integer
    gamesMadeCount = models.IntegerField(default=0)
    # maximum amount of games allowed to be made
    gamesMadeMaxCount = models.IntegerField(default=MAX_AUTHORED_GAMES)

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

    # module binary FIXME REMOVE THIS
    type_module_bytes = models.BinaryField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__game_module = None

    def save(self, *args, **kwargs):
        if not self.createdOn:
            # check if game type count exceeds desired maximum
            if GameType.objects.filter(creator=self.creator).count() > MAX_AUTHORED_GAMES:
                raise TooManyGameTypesWarning

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
                raise UrlInvalidError
            # try cloning
            self.getGameModule()
        return super(GameType, self).save(*args, **kwargs)

    def getGameModule(self):
        """
        Gets module from binary
        :return: module
        """
        if self.__game_module is not None:
            return self.__game_module
        gt_id = self.game_type_id
        # clone
        if not os.path.exists(GAME_TYPES_FOLDER):
            try:
                logger.info("Cloning {" + gt_id + "}...")
                git('clone', self.git_url, GAME_TYPES_FOLDER + gt_id)
            except Exception as e:
                logger.error("Cloning of {" + gt_id + "} failed! Details: {" + str(e) + "}")
                raise RuntimeError(str(e))
            else:
                logger.info("Cloning of {" + gt_id + "} is complete!")
        # TODO make it work with src/setup.py stuff
        # save
        module = import_module('cavoke_app.game_modules.' + gt_id)
        self.__game_module = module
        return module
