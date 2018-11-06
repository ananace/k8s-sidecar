FROM python:3.7-slim

RUN pip install kubernetes==8.0.0

COPY sidecar/sidecar.py /app/

ENV PYTHONUNBUFFERED=1

WORKDIR /app/

CMD [ "python", "-u", "/app/sidecar.py" ]
