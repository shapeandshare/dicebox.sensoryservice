# https://hub.docker.com/r/tiangolo/uwsgi-nginx/
FROM tiangolo/uwsgi-nginx:python2.7

WORKDIR /app

COPY ./app /app
COPY ./dicebox/lib /app/lib

RUN pip install -r requirements.txt \
    && useradd -M -U -u 1000 sensoryservice \
    && chown -R sensoryservice /app

EXPOSE 80
