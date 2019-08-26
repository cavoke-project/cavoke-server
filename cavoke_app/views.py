import logging
import multiprocessing
import uuid
from multiprocessing import Process
from typing import Callable

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

from cavoke_server import db, notifyAdmin
from .models import GameSession, GameType
from .serializers import *
from .errormessages import *
from .exceptions import *
from .config import *

logger = logging.getLogger(__name__)
validator = URLValidator()


@api_view(["GET"])
@authentication_classes(())
def health(request):
    """
    Health function. Always returns ok
    :param request: request
    :return: response
    """
    return HttpResponse("OK")


@api_view(["GET"])
def newGameSession(request):
    """
    Creates new game session for an authenticated user.
    :param request: request with game_type_id in query
    :return: response
    """
    # get uid
    uid = request.auth['uid']
    # check query
    data = parse(request.query_params)
    try:
        game_type_id = str(data['game_type_id'])
    except KeyError:
        return error_response(NOT_ENOUGH_PARAMS, HTTP_400_BAD_REQUEST)

    # create model
    gs = GameSession(game_type=GameType.objects.get(game_type_id=game_type_id), player_uid=uid)
    try:
        gs.save()
    except TooManyGameSessionsWarning:
        return error_response(MAX_GAME_SESSIONS, HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(str(e))
        return error_response("Error occurred when processing the input data.", HTTP_400_BAD_REQUEST)

    logger.info("New Game Session started by " + uid)

    return ok_response({"game": GameSessionSerializer(gs).data})


@api_view(["GET"])
def newGameType(request):
    """
    Creates new game session for an authenticated non-anonymous user.
    :param request: request with parameters for GameType constructor
    :return: response
    """
    # get uid
    uid = request.auth['uid']

    # check if anonymous
    if isAnonymous(uid):
        return error_response(ANONYMOUS_FORBIDDEN, HTTP_403_FORBIDDEN)

    # get query params
    data = parse(request.query_params)
    user = userByUID(uid)
    data['creator'] = uid
    data['creator_display_name'] = user.username

    # create game_type_id
    # .replace() because it will be the name of package in game_modules
    data['game_type_id'] = randomUUID()

    # create model
    gts = GameTypeSerializer(data=data)
    if not gts.is_valid():
        return error_response(NOT_ENOUGH_PARAMS, HTTP_400_BAD_REQUEST)
    gt = gts.createInstance()

    # check if author hasn't got too many games
    if user.profile.gamesMadeCount >= user.profile.gamesMadeMaxCount:
        return error_response(AUTHOR_MAX_GAMES, HTTP_400_BAD_REQUEST)
    user.profile.gamesMadeCount += 1
    user.profile.lastGameCreatedOn = timezone.now()
    user.save()

    # gen token for moderator
    modtoken = randomUUID()

    gameId = gt.game_type_id
    gitUrl = gt.git_url

    # check if valid url
    try:
        validator(gitUrl)
        if gitUrl[-4:] != '.git':
            raise ValidationError
    except ValidationError:
        return error_response(WRONG_URL, HTTP_400_BAD_REQUEST)

    # prepare dict with game type info
    rdict = GameTypeSerializer(gt).data

    # INFO we do this as gt.save() wasn't called yet and createdOn isn't initialized
    rdict['createdOn'] = timezone.now()

    # add modtoken to copy of rdict
    secret_rdict = rdict.copy()
    secret_rdict['modtoken'] = modtoken
    # save secret rdict
    db.collection('pending_games').document(gameId).set(secret_rdict)

    # add game to pending games
    doc_ref = db.collection('users').document(uid)
    if doc_ref.get()._exists:
        doc_ref.update({'pending_games': ArrayUnion([rdict])})
    else:
        doc_ref.set({'pending_games': [rdict]})

    # notify moderator
    host = request._request._current_scheme_host
    # TODO improve security
    message = ('New game for moderation check:'
               '\n\n' +
               str(rdict) +
               '\n\n'
               'https://console.firebase.google.com/project/cavoke-firebase/database/firestore/'
               'data~2Fpending_games~2F' + gameId +
               '\n\n'
               'To **approve** click ' + host + '/v1/adminMethods/approveGame?game_type_id=' + gameId + '&token=' + modtoken +
               '\n'
               'To **decline** click ' + host + '/v1/adminMethods/declineGame?game_type_id=' + gameId + '&token=' + modtoken
               )
    notifyAdmin(message)

    return ok_response(rdict)


@api_view(["GET"])
@authentication_classes(())
def approveGame(request):
    """
    Approves game for moderator
    :param request: request with game_type_id and token
    :return: response
    """
    # TODO improve security
    # get query
    data = parse(request.query_params)
    try:
        game_type_id = str(data['game_type_id'])
        modtoken = str(data['token'])
    except KeyError:
        return error_response(NOT_ENOUGH_PARAMS, HTTP_400_BAD_REQUEST)

    # check if the game exists
    gdoc = db.collection('pending_games').document(game_type_id).get()
    if not gdoc._exists:
        return error_response(GAME_NOT_FOUND, HTTP_400_BAD_REQUEST)

    # check if right token
    gdict: dict = gdoc.to_dict()
    if gdict['modtoken'] != modtoken:
        return error_response(WRONG_TOKEN, HTTP_403_FORBIDDEN)

    # get uid
    uid = gdict['creator']

    # save game type to database
    serializer = GameTypeSerializer(data=gdict)
    if not serializer.is_valid():
        return error_response(ERROR_OCCURRED, HTTP_500_INTERNAL_SERVER_ERROR)
    serializer.save()

    # save stats for user
    gdict.pop('modtoken')
    db.collection('pending_games').document(game_type_id).delete()
    db.collection('users').document(uid).update({u'pending_games': ArrayRemove([gdict])})
    db.collection('users').document(uid).update({u'authored_games': ArrayUnion([gdict])})

    return ok_response(gdict)


@api_view(["GET"])
@authentication_classes(())
def declineGame(request):
    """
    Declines game for moderator
    :param request: request with game_type_id and token
    :return: response
    """
    # get query
    data = parse(request.query_params)
    try:
        game_type_id = str(data['game_type_id'])
        modtoken = str(data['token'])
    except KeyError:
        return error_response(NOT_ENOUGH_PARAMS, HTTP_400_BAD_REQUEST)

    # check if game exists
    gdoc = db.collection('pending_games').document(game_type_id).get()
    if not gdoc._exists:
        return error_response(GAME_NOT_FOUND, HTTP_400_BAD_REQUEST)

    # check if right token
    gdict = gdoc.to_dict()
    if gdict['modtoken'] != modtoken:
        return error_response(WRONG_TOKEN, HTTP_403_FORBIDDEN)
    # get uid
    uid = gdict['creator']

    # save stats
    db.collection('pending_games').document(game_type_id).delete()
    db.collection('users').document(uid).update({u'pending_games': ArrayRemove([gdict])})

    # free up the slot for game
    # TODO make atomic
    user = userByUID(uid)
    user.profile.gamesMadeCount -= 1
    user.save()

    return ok_response()


@api_view(["GET"])
def getAuthor(request):
    """
    Gets info about authored games, that authenticated user has made.
    :param request: request
    :return: response
    """
    # get id
    uid = request.auth["uid"]

    # get data
    gdoc = db.collection('users').document(uid).get()
    gdict = gdoc.to_dict() if gdoc.to_dict() else {}
    f = lambda b: tryGetListFromDict(gdict, b)
    authored, pending = f("authored_games"), f("pending_games")

    return ok_response({
        "authored_games": authored,
        "pending_games": pending
    })


@api_view(["GET"])
def click(request):
    """
    Click on unit in game session
    :param request: request with game_id and unit_clicked
    :return: response
    """
    # get uid
    uid = request.auth["uid"]

    # get query
    data = parse(request.query_params)
    try:
        gameId = str(data['game_id'])
        unitClicked = str(data['unit_clicked'])
    except KeyError:
        return error_response(NOT_ENOUGH_PARAMS, HTTP_400_BAD_REQUEST)

    # check if user is the owner
    try:
        gs = GameSession.objects.get(game_session_id=gameId)
    except GameSession.DoesNotExist:
        return error_response(GAME_NOT_FOUND, HTTP_400_BAD_REQUEST)
    if gs.player_uid != uid:
        return error_response(NOT_OWNER, HTTP_403_FORBIDDEN)

    # stats
    user = userByUID(uid)
    user.profile.lastPlayedOn = timezone.now()

    # try clicking
    try:
        response = run_with_limited_time(gs.getCavokeGame().clickUnitId, (unitClicked,))
    except cavoke.exceptions.UnitNotFoundError:
        # if unit wasn't found
        return error_response(UNIT_NOT_FOUND, HTTP_400_BAD_REQUEST)
    except TimeoutError:
        # in case of timeout
        return error_response(TIMEOUT_ERROR, HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        # anything else
        message = "Error occurred during game code execution: [" + str(e) + "]. Contact developer"
        logger.error(message)
        return error_response(message, HTTP_500_INTERNAL_SERVER_ERROR)

    return ok_response({"game": response})


@api_view(["GET"])
def dragTo(request):
    """
    Drag unit to unit
    NOT IMPLEMENTED
    """
    # TODO DO
    return error_response(NOT_IMPLEMENTED, HTTP_501_NOT_IMPLEMENTED)


@api_view(["GET"])
def getSessions(request):
    """
    Gets all sessions for an authenticated user
    :param request: request
    :return: response
    """
    # get uid
    uid = request.auth["uid"]

    # get data
    gs_list = list(GameSession.objects.filter(player_uid=uid))
    gs_info_list = [GameSessionSerializer(gs).data for gs in gs_list]

    return ok_response({'game_sessions': gs_info_list})


@api_view(["GET"])
def getSession(request):
    """
    Gets info about a specific game session
    :param request: request with game_id
    :return: response
    """
    # get uid
    uid = request.auth["uid"]

    # get query
    data = parse(request.query_params)
    try:
        gameId = str(data['game_id'])
    except KeyError:
        return error_response(NOT_ENOUGH_PARAMS, HTTP_400_BAD_REQUEST)

    # check if user is the owner
    try:
        gs = GameSession.objects.get(game_session_id=gameId)
    except GameSession.DoesNotExist:
        return error_response(GAME_NOT_FOUND, HTTP_400_BAD_REQUEST)
    if gs.player_uid != uid:
        return error_response(NOT_OWNER, HTTP_403_FORBIDDEN)

    # stats
    user = userByUID(uid)
    user.profile.lastPlayedOn = timezone.now()

    # try getting response from cavoke.Game
    try:
        response = run_with_limited_time(gs.getCavokeGame().getResponse, ())
    except TimeoutError:
        # in case of timeout, but how?
        return error_response(TIMEOUT_ERROR, HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        # in case of any other error, but hOw??
        message = "Error occurred during game code execution: [" + str(e) + "]. Contact the developer."
        logger.error(message)
        return error_response(message, HTTP_500_INTERNAL_SERVER_ERROR)

    return ok_response({"data": GameSessionSerializer(gs).data, "game": response})


@api_view(["GET"])
@authentication_classes(())
def getTypes(request):
    """
    Gets available types for playing
    :param request: request
    :return: response
    """
    return ok_response({'game_types': GameTypeSerializer(GameType.objects.all(), many=True).data})

# TODO delete game session
