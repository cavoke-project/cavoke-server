# from celery.schedules import crontab
# from celery.task import periodic_task
# from django.utils import timezone
# from cavoke_app.models import GameSession
#
#
# @periodic_task(run_every=crontab(minute='*/1'))
# def delete_old_foos():
#     # Query all the foos in our database
#     gss = GameSession.objects.all()
#
#     # Iterate through them
#     for gs in gss:
#
#         # If the expiration date is bigger than now delete it
#         if gs.expiresOn < timezone.now():
#             gs.delete()
#             # log deletion
#     return "completed deleting foos at {}".format(timezone.now())
