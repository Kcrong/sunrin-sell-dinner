migrate: python manage.py db init; python manage.py db migrate;python manage.py db upgrade
web: gunicorn -w 4 -b "0.0.0.0:$PORT" main:app