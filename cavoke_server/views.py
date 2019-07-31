from django.http import HttpResponse
from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.parsers import JSONParser


# Create your views here.
def index(request):
    return HttpResponse('Welcome to cavoke API. See methods to talk to the server.')
