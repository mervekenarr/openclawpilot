FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir googlesearch-python
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

EXPOSE 8501
EXPOSE 8502

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

CMD ["bash", "start.sh"]
