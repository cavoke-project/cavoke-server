import logging
import multiprocessing
import uuid
from multiprocessing import Process
from typing import Callable
import eventlet

import cavoke.exceptions
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils import timezone
from drf_firebase_auth_cavoke.models import FirebaseUser
from google.cloud.firestore_v1 import ArrayUnion, ArrayRemove
from rest_framework.decorators import api_view, authentication_classes
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.status import *

from .exceptions import *

"""
Time delta, that game sessions should be valid for
"""
GAMESESSION_VALID_FOR = timezone.timedelta(weeks=1)

"""
Maximum number of game types each user can author
"""
MAX_AUTHORED_GAMES = 10

"""
Maximum number of active game sessions each user can have
"""
MAX_ACTIVE_GAME_SESSIONS = 10

"""
Folder used for storing game types
"""
GAME_TYPES_FOLDER = "./cavoke_app/game_modules/"

"""
Timeout for cavoke game session in seconds
"""
TIMEOUT_FOR_GAME = 10


# eventlet.monkey_patch()

def randomUUID():
    return uuid.uuid4().__str__().replace('-', '')


def error_response(message: str, error_code) -> Response:
    """
    Makes error http response with explanation and error code
    :param message: message for client
    :param error_code: http error code as rest_framework.status
    :return: response
    """
    return Response({"status": "Error", "message": message}, error_code)


def ok_response(answer: dict = {}) -> Response:
    """
    Makes ok http response
    :param answer: data for client
    :return: response
    """
    return Response({"status": "OK", "response": answer}, HTTP_200_OK)


def tryGetListFromDict(d: dict, key: str):
    """
    Gets element from dict, if not present returns empty list
    :param d: dict
    :param key: key for element
    :return: element or empty list
    """
    try:
        return d[key]
    except KeyError:
        return []


def userByUID(uid: str) -> User:
    """
    Gets User by uid
    :param uid: uid as str
    :return: User as django.contrib.auth.models.User
    """
    fu = FirebaseUser.objects.get(uid=uid)
    user = User.objects.get(firebase_user=fu)
    return user


def run_with_limited_time(func: Callable, args: tuple):
    """Runs a function with time limit

    :param func: The function to run
    :param args: The functions args, given as tuple
    :return: True if the function ended successfully. False if it was terminated.
    """
    timeout = eventlet.Timeout(TIMEOUT_FOR_GAME, TimeoutError)
    r = func(*args)
    timeout.cancel()
    return r


def isAnonymous(uid: str) -> bool:
    """
    Checks if user by uid is anonymous
    :param uid: user's uid
    :return: true if user is anonymous, else - false
    """
    return FirebaseUser.objects.get(uid=uid).isAnonymous


def parse(query: QuerySet) -> dict:
    """
    Parses queryset for params.
    :param query: queryset
    :return: dictionary, that corresponds to queryset
    """
    r = {}
    for k, v in dict(query).items():
        if isinstance(v, list):
            r[k] = v[0]
        else:
            r[k] = v
    return r
