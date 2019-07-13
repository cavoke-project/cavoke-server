from django.http import HttpResponse

from rest_framework import generics
from rest_framework import permissions
from rest_framework.response import Response

from .models import GameSession

from django.contrib.auth import authenticate
from django.views.decorators.csrf import csrf_exempt
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.status import *
from rest_framework.response import Response


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
def newGame(request):
    uid = request.auth['uid']
    data = request.query_params
    try:
        game_type_id = str(data['game_type_id'][0])
    except KeyError:
        return error_response("Wrong params", HTTP_400_BAD_REQUEST)

    gs = GameSession(game_type_id=game_type_id, player_uid=uid)
    gs.save()
    return ok_response({'gameId': gs.game_session_id})
