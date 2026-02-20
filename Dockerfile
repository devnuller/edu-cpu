FROM python:3.12-slim

WORKDIR /app

COPY assembler.py simulator.py ./
COPY ctf/flag.hex ctf/flag.hex
COPY web/ web/

RUN pip install --no-cache-dir flask

EXPOSE 8080

CMD ["python", "web/server.py"]
