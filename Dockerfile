FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
	&& rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry

# Copy the project files
COPY pyproject.toml poetry.lock ./

# Install dependencies using Poetry
RUN poetry config virtualenvs.create false && poetry install --no-root --only main

# Copy the application code
COPY app.py .

# Set the CMD to your handler
CMD [ "python", "app.py" ]