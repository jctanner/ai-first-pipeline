FROM python:3.13-slim

RUN pip install --no-cache-dir Flask requests kubernetes \
    && useradd --create-home --shell /usr/sbin/nologin fullsend

WORKDIR /app
COPY src/fullsend-dashboard/ /app/
RUN chown -R fullsend:fullsend /app

USER fullsend
ENV PYTHONUNBUFFERED=1
EXPOSE 5000
CMD ["python", "app.py"]
