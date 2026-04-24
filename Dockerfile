FROM python:3.11-slim

ENV TZ=Australia/Melbourne
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
RUN mkdir -p /app/instance

EXPOSE 5000
ENV FLASK_DEBUG=0
CMD ["python", "app.py"]
