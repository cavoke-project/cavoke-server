import logging
import multiprocessing
import uuid
from multiprocessing import Process
from typing import Callable

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import HttpResponse
from django.contrib.auth import authenticate
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from google.cloud.firestore_v1 import ArrayUnion, ArrayRemove

from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.serializers import Serializer
from rest_framework.status import *
from rest_framework.response import Response
from rest_framework import generics
from rest_framework import permissions
from rest_framework.response import Response

from drf_firebase_auth.models import FirebaseUser

from .models import GameSession
from .gamestorage import game_session_dict
from cavoke_server import db, notifyAdmin

import cavoke.exceptions

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


# API methods
@csrf_exempt
@api_view(["GET"])
@authentication_classes(())
def health(request):
    return HttpResponse("OK")


@csrf_exempt
@api_view(["GET"])
def newGameSession(request):
    uid = request.auth['uid']
    data = request.query_params
    try:
        game_type_id = str(data['game_type_id'])
    except KeyError:
        return error_response("Not enough params", HTTP_400_BAD_REQUEST)

    gs = GameSession(game_type_id=game_type_id, player_uid=uid)
    try:
        gs.save()
    except Exception as e:
        logger.error(str(e))
        return error_response("Error occured when processing the input data, check your url", HTTP_400_BAD_REQUEST)
    logging.INFO("New Game Session started by " + uid)
    return ok_response({"game": Serializer(gs).data})


@csrf_exempt
@api_view(["GET"])
def newGameType(request):
    # get request data
    uid = request.auth['uid']
    data = request.query_params
    try:
        gitUrl = str(data['gitUrl'])
    except KeyError:
        return error_response("Not enough params", HTTP_400_BAD_REQUEST)

    user = userByUID(uid)
    if user.profile.gamesMadeCount >= user.profile.gamesMadeMaxCount:
        return error_response("User reached max authored games count", HTTP_417_EXPECTATION_FAILED)
    user.profile.gamesMadeCount += 1
    user.save()

    gameId = uuid.uuid4().__str__()
    modtoken = uuid.uuid4().__str__()

    try:
        validator(gitUrl)
        if gitUrl[-4:] != '.git':
            raise ValidationError
    except ValidationError:
        return error_response("Provided url is invalid!", HTTP_400_BAD_REQUEST)

    rdict = {
        'gitUrl': gitUrl,
        'creator': uid,
        'modtoken': modtoken
    }

    db.collection('pending_games').document(gameId).set(rdict)
    doc_ref = db.collection('users').document(uid)
    if doc_ref.get()._exists:
        doc_ref.update({'pending_games': ArrayUnion([gameId])})
    else:
        doc_ref.set({'pending_games': [gameId]})

    host = request._request._current_scheme_host
    message = ('New game for moderation check:'
               '\n\n' +
               str(rdict) +
               '\n\n'
               'https://console.firebase.google.com/project/cavoke-firebase/database/firestore/'
               'data~2Fpending_games~2F' + gameId +
               '\n\n'
               'To **approve** click ' + host + '/v1/adminMethods/approveGame?gameId=' + gameId + '&token=' + modtoken +
               '\n'
               'To **decline** click ' + host + '/v1/adminMethods/declineGame?gameId=' + gameId + '&token=' + modtoken
               )
    notifyAdmin(message)
    return ok_response({'gameId': gameId})


@csrf_exempt
@api_view(["GET"])
@authentication_classes(())
def approveGame(request):
    data = request.query_params
    try:
        gameId = str(data['gameId'])
        modtoken = str(data['token'])
    except KeyError:
        return error_response("Not enough params", HTTP_400_BAD_REQUEST)

    gdoc = db.collection('pending_games').document(gameId).get()
    if not gdoc._exists:
        return error_response("No such game", HTTP_400_BAD_REQUEST)
    gdict: dict = gdoc.to_dict()
    if gdict['modtoken'] != modtoken:
        return error_response("Wrong token!", HTTP_403_FORBIDDEN)
    uid = gdict['creator']

    db.collection('pending_games').document(gameId).delete()
    db.collection('users').document(uid).update({u'pending_games': ArrayRemove([gameId])})

    db.collection('users').document(uid).update({u'authored_games': ArrayUnion([gameId])})
    gdict.pop('modtoken')
    db.collection('games').document(gameId).set(gdict)
    return ok_response()


@csrf_exempt
@api_view(["GET"])
@authentication_classes(())
def declineGame(request):
    data = request.query_params
    try:
        gameId = str(data['gameId'])
        modtoken = str(data['token'])
    except KeyError:
        return error_response("Not enough params", HTTP_400_BAD_REQUEST)

    gdoc = db.collection('pending_games').document(gameId).get()
    if not gdoc._exists:
        return error_response("No such game", HTTP_400_BAD_REQUEST)
    gdict = gdoc.to_dict()
    if gdict['modtoken'] != modtoken:
        return error_response("Wrong token!", HTTP_403_FORBIDDEN)
    uid = gdict['creator']

    db.collection('pending_games').document(gameId).delete()
    db.collection('users').document(uid).update({u'pending_games': ArrayRemove([gameId])})

    # TODO make atomic
    user = userByUID(uid)
    user.profile.gamesMadeCount -= 1
    user.save()
    return ok_response()


@csrf_exempt
@api_view(["GET"])
def getAuthor(request):
    uid = request.auth["uid"]
    gdoc = db.collection('users').document(uid).get()
    if not gdoc._exists:
        return error_response("No such user", HTTP_400_BAD_REQUEST)
    gdict = gdoc.to_dict()
    f = lambda b: tryGetListFromDict(gdict, b)
    authored, pending = f("authored_games"), f("pending_games")
    return ok_response({
        "authored_games": authored,
        "pending_games": pending
    })


@csrf_exempt
@api_view(["GET"])
def click(request):
    uid = request.auth["uid"]
    data = request.query_params
    try:
        gameId = str(data['gameId'])
        unitClicked = str(data['unitClicked'])
    except KeyError:
        return error_response("Not enough params", HTTP_400_BAD_REQUEST)

    # check if user is the owner
    try:
        gs = GameSession.objects.get(game_session_id=gameId)
    except GameSession.DoesNotExist:
        return error_response("No such gameId", HTTP_400_BAD_REQUEST)
    if gs.player_uid != uid:
        return error_response("Not your game!", HTTP_403_FORBIDDEN)

    # stats
    user = userByUID(uid)
    user.profile.lastPlayedOn = timezone.now()

    game_session_dict[gameId][1].acquire()
    try:
        response = run_with_limited_time(game_session_dict[gameId][0].clickUnitId, (unitClicked,))
    except cavoke.exceptions.UnitNotFoundError:
        return error_response("No such unit", HTTP_400_BAD_REQUEST)
    except TimeoutError:
        return error_response("Timeout error", HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        message = "Error occurred during game code execution: [" + str(e) + "]. Contact developer"
        logger.error(message)
        return error_response(message, HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        game_session_dict[gameId][1].release()
    return ok_response({"game": response})


@csrf_exempt
@api_view(["GET"])
def getState(request):
    uid = request.auth["uid"]
    data = request.query_params
    try:
        gameId = str(data['gameId'])
    except KeyError:
        return error_response("Not enough params", HTTP_400_BAD_REQUEST)

    # check if user is the owner
    try:
        gs = GameSession.objects.get(game_session_id=gameId)
    except GameSession.DoesNotExist:
        return error_response("No such gameId", HTTP_400_BAD_REQUEST)
    if gs.player_uid != uid:
        return error_response("Not your game!", HTTP_403_FORBIDDEN)

    # stats
    user = userByUID(uid)
    user.profile.lastPlayedOn = timezone.now()

    game_session_dict[gameId][1].acquire()
    try:
        response = game_session_dict[gameId][0].getResponse()
        run_with_limited_time(game_session_dict[gameId][0].getResponse, ())
    except TimeoutError:
        return error_response("Timeout error", HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        message = "Error occurred during game code execution: [" + str(e) + "]. Contact the developer."
        logger.error(message)
        return error_response(message, HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        game_session_dict[gameId][1].release()
    return ok_response({"game": response})


@csrf_exempt
@api_view(["GET"])
def dragTo(request):
    return error_response("Not implemented!", HTTP_501_NOT_IMPLEMENTED)


@csrf_exempt
@api_view(["GET"])
def getSessions(request):
    uid = request.auth["uid"]
    gs_list = list(GameSession.objects.filter(player_uid=uid))
    gs_info_list = [Serializer(gs).data for gs in gs_list]
    return ok_response({'game_sessions': gs_info_list})


@csrf_exempt
@api_view(["GET"])
def getSession(request):
    uid = request.auth["uid"]
    data = request.query_params
    try:
        gameId = str(data['gameId'])
    except KeyError:
        return error_response("Not enough params", HTTP_400_BAD_REQUEST)

    try:
        gs = GameSession.objects.get(game_session_id=gameId)
    except GameSession.DoesNotExist:
        return error_response("Game session doesn't exist", HTTP_400_BAD_REQUEST)

    return ok_response({"game": Serializer(gs).data})

