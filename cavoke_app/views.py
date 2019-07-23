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
from .gamestorage import game_session_dict
from .models import GameSession, GameType
from .serializers import *
from .errormessages import *

logger = logging.getLogger(__name__)
validator = URLValidator()

TIMEOUT_FOR_GAME = 10


def error_response(message: str, error_code):
    return Response({"status": "Error", "message": message}, error_code)


def ok_response(answer: dict = {}):
    return Response({"status": "OK", "response": answer}, HTTP_200_OK)


def tryGetListFromDict(d: dict, key: str):
    try:
        return d[key]
    except KeyError:
        return []


def userByUID(uid: str) -> User:
    fu = FirebaseUser.objects.get(uid=uid)
    user = User.objects.get(firebase_user=fu)
    return user


def _ltrun(f: Callable, args: tuple, return_dict: dict):
    r = f(*args)
    return_dict[''] = r


def run_with_limited_time(func: Callable, args: tuple):
    """Runs a function with time limit

    :param func: The function to run
    :param args: The functions args, given as tuple
    :param kwargs: The functions keywords, given as dict
    :param time: The time limit in seconds
    :return: True if the function ended successfully. False if it was terminated.
    """
    manager = multiprocessing.Manager()
    rdict = manager.dict()
    p = Process(target=_ltrun, args=(func, args, rdict), kwargs={})
    p.start()
    p.join(TIMEOUT_FOR_GAME)
    if p.is_alive():
        p.terminate()
        raise TimeoutError
    return rdict['']


def isAnonymous(uid: str):
    return FirebaseUser.objects.get(uid=uid).isAnonymous


def parse(query: QuerySet):
    r = {}
    for k, v in dict(query).items():
        if isinstance(v, list):
            r[k] = v[0]
        else:
            r[k] = v
    return r


# API methods
@api_view(["GET"])
@authentication_classes(())
def health(request):
    return HttpResponse("OK")


@api_view(["GET"])
def newGameSession(request):
    uid = request.auth['uid']
    data = parse(request.query_params)
    try:
        game_type_id = str(data['game_type_id'])
    except KeyError:
        return error_response(NOT_ENOUGH_PARAMS, HTTP_400_BAD_REQUEST)

    gs = GameSession(game_type=GameType.objects.get(game_type_id=game_type_id), player_uid=uid)
    try:
        gs.save()
    except Exception as e:
        logger.error(str(e))
        return error_response("Error occurred when processing the input data.", HTTP_400_BAD_REQUEST)
    logging.INFO("New Game Session started by " + uid)
    return ok_response({"game": GameSessionSerializer(gs).data})


@api_view(["GET"])
def newGameType(request):
    # get request data
    uid = request.auth['uid']

    if isAnonymous(uid):
        return error_response(ANONYMOUS_FORBIDDEN, HTTP_403_FORBIDDEN)

    data = parse(request.query_params)
    user = userByUID(uid)
    try:
        _uid = data['creator']
        if _uid != uid:
            return error_response(NOT_OWNER, HTTP_400_BAD_REQUEST)
    except KeyError:
        data['creator'] = uid
    data['creator_display_name'] = user.username
    # replace as it will be the name of package in game_modules
    data['game_type_id'] = uuid.uuid4().__str__().replace('-', '')

    gts = GameTypeSerializer(data=data)
    if not gts.is_valid():
        return error_response(NOT_ENOUGH_PARAMS, HTTP_400_BAD_REQUEST)
    gt = gts.createInstance()

    if user.profile.gamesMadeCount >= user.profile.gamesMadeMaxCount:
        return error_response(AUTHOR_MAX_GAMES, HTTP_400_BAD_REQUEST)
    user.profile.gamesMadeCount += 1
    user.profile.lastGameCreatedOn = timezone.now()
    user.save()

    modtoken = uuid.uuid4().__str__()
    gameId = gt.game_type_id
    gitUrl = gt.git_url

    try:
        validator(gitUrl)
        if gitUrl[-4:] != '.git':
            raise ValidationError
    except ValidationError:
        return error_response(WRONG_URL, HTTP_400_BAD_REQUEST)

    rdict = GameTypeSerializer(gt).data
    # INFO we do this as gt.save() wasn't called yet and createdOn isn't initialized
    rdict['createdOn'] = timezone.now()

    secret_rdict = rdict.copy()
    secret_rdict['modtoken'] = modtoken
    db.collection('pending_games').document(gameId).set(secret_rdict)

    doc_ref = db.collection('users').document(uid)
    if doc_ref.get()._exists:
        doc_ref.update({'pending_games': ArrayUnion([rdict])})
    else:
        doc_ref.set({'pending_games': [rdict]})

    host = request._request._current_scheme_host
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
    data = parse(request.query_params)
    try:
        game_type_id = str(data['game_type_id'])
        modtoken = str(data['token'])
    except KeyError:
        return error_response(NOT_ENOUGH_PARAMS, HTTP_400_BAD_REQUEST)

    gdoc = db.collection('pending_games').document(game_type_id).get()
    if not gdoc._exists:
        return error_response(GAME_NOT_FOUND, HTTP_400_BAD_REQUEST)
    gdict: dict = gdoc.to_dict()
    if gdict['modtoken'] != modtoken:
        return error_response(WRONG_TOKEN, HTTP_403_FORBIDDEN)
    uid = gdict['creator']

    gdict.pop('modtoken')
    serializer = GameTypeSerializer(data=gdict)
    if not serializer.is_valid():
        return error_response(ERROR_OCCURRED, HTTP_500_INTERNAL_SERVER_ERROR)
    serializer.save()

    db.collection('pending_games').document(game_type_id).delete()
    db.collection('users').document(uid).update({u'pending_games': ArrayRemove([game_type_id])})
    db.collection('users').document(uid).update({u'authored_games': ArrayUnion([game_type_id])})
    return ok_response(gdict)


@api_view(["GET"])
@authentication_classes(())
def declineGame(request):
    data = parse(request.query_params)
    try:
        game_type_id = str(data['game_type_id'])
        modtoken = str(data['token'])
    except KeyError:
        return error_response(NOT_ENOUGH_PARAMS, HTTP_400_BAD_REQUEST)

    gdoc = db.collection('pending_games').document(game_type_id).get()
    if not gdoc._exists:
        return error_response(GAME_NOT_FOUND, HTTP_400_BAD_REQUEST)
    gdict = gdoc.to_dict()
    if gdict['modtoken'] != modtoken:
        return error_response(WRONG_TOKEN, HTTP_403_FORBIDDEN)
    uid = gdict['creator']

    db.collection('pending_games').document(game_type_id).delete()
    db.collection('users').document(uid).update({u'pending_games': ArrayRemove([game_type_id])})

    # TODO make atomic
    user = userByUID(uid)
    user.profile.gamesMadeCount -= 1
    user.save()
    return ok_response()


@api_view(["GET"])
def getAuthor(request):
    uid = request.auth["uid"]
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
    uid = request.auth["uid"]
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

    game_session_dict[gameId][1].acquire()
    try:
        response = run_with_limited_time(game_session_dict[gameId][0].clickUnitId, (unitClicked,))
    except cavoke.exceptions.UnitNotFoundError:
        return error_response(UNIT_NOT_FOUND, HTTP_400_BAD_REQUEST)
    except TimeoutError:
        return error_response(TIMEOUT_ERROR, HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        message = "Error occurred during game code execution: [" + str(e) + "]. Contact developer"
        logger.error(message)
        return error_response(message, HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        game_session_dict[gameId][1].release()
    return ok_response({"game": response})


@api_view(["GET"])
def dragTo(request):
    return error_response(NOT_IMPLEMENTED, HTTP_501_NOT_IMPLEMENTED)


@api_view(["GET"])
def getSessions(request):
    uid = request.auth["uid"]
    gs_list = list(GameSession.objects.filter(player_uid=uid))
    gs_info_list = [GameSessionSerializer(gs).data for gs in gs_list]
    return ok_response({'game_sessions': gs_info_list})


@api_view(["GET"])
def getSession(request):
    uid = request.auth["uid"]
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

    game_session_dict[gameId][1].acquire()
    try:
        response = game_session_dict[gameId][0].getResponse()
        run_with_limited_time(game_session_dict[gameId][0].getResponse, ())
    except TimeoutError:
        return error_response(TIMEOUT_ERROR, HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        message = "Error occurred during game code execution: [" + str(e) + "]. Contact the developer."
        logger.error(message)
        return error_response(message, HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        game_session_dict[gameId][1].release()

    return ok_response({"data": GameSessionSerializer(gs).data, "game": response})


@api_view(["GET"])
@authentication_classes(())
def getTypes(request):
    return ok_response({'game_types': GameTypeSerializer(GameType.objects.all(), many=True).data})

