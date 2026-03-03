FROM python:3.12-slim

WORKDIR /factory/webapp

COPY webapp/requirements.txt /factory/webapp/
RUN pip install --no-cache-dir -r requirements.txt

# Copy webapp code
COPY webapp/ /factory/webapp/
# Copy reused lager-factory library modules (must be at /factory/lager/
# so that relative path resolution in config.py and nets_reader.py works)
COPY lager/ /factory/lager/

ENV PYTHONPATH=/factory/webapp
ENV FLASK_ENV=production

# Data directory for persistent scripts and history
RUN mkdir -p /factory/webapp/data/scripts /factory/webapp/data/history
ENV LAGER_WEBAPP_DATA_DIR=/factory/webapp/data
VOLUME /factory/webapp/data

ENV PORT=5001
EXPOSE 5001

CMD ["python", "run.py"]
