FROM python:3.10-slim

RUN pip install pipenv

COPY . /src

WORKDIR '/src/'

RUN pipenv install --python /usr/local/bin/python

EXPOSE 9090

CMD [ "pipenv", "run", "python", "run.py" ]
