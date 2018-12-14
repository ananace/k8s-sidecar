FROM python:3.7-slim

LABEL Version=latest \
      Name=ananace/k8s-sidecar

RUN apt-get -y update \
 && apt-get -y install patch --no-install-recommends \
 && apt-get -y clean \
 && rm -rf /var/lib/ap/lists \
 && pip install kubernetes==8.0.0

COPY k8s-watch.patch /usr/local/lib/python3.7/site-packages/kubernetes
RUN cd /usr/local/lib/python3.7/site-packages/kubernetes/ && patch -p1 -i k8s-watch.patch

COPY sidecar/sidecar.py /app/

ENV PYTHONUNBUFFERED=1

WORKDIR /app/

CMD [ "python", "-u", "/app/sidecar.py" ]
