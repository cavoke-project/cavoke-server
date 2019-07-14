import logging

from django.http import HttpResponse
from django.contrib.auth import authenticate
from django.views.decorators.csrf import csrf_exempt

from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.status import *
from rest_framework.response import Response
from rest_framework import generics
from rest_framework import permissions
from rest_framework.response import Response

from drf_firebase_auth.models import FirebaseUser

from .models import GameSession

logger = logging.getLogger(__name__)


def error_response(message: str, error_code):
    return Response({"status": "Error", "message": message}, error_code)


def ok_response(answer: dict):
    return Response({"status": "OK", "response": answer}, HTTP_200_OK)


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
    return ok_response({'gameId': gs.game_session_id})


@csrf_exempt
@api_view(["GET"])
def newGameType(request):
    uid = request.auth['uid']
    data = request.query_params
    try:
        gitUrl = str(data['game_git_url'])
    except KeyError:
        return error_response("Not enough params", HTTP_400_BAD_REQUEST)
    # TODO complete: get user by uid or smth and check games count
    # TODO: add gitUrl to firebase
