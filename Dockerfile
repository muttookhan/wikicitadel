# WikiCitadel — demo container
# Builds the Lens from the seed corpus and serves it as static files.
# The seed wiki is fictional; replace wiki/ + raw/ with your own corpus.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/wikicitadel
COPY . /srv/wikicitadel

# The Lens build stamps itself from git; a container copy has no .git,
# so initialise a throwaway one for the build stamp only.
RUN git init -q . && git add -A && \
    git -c user.name="WikiCitadel Demo" -c user.email="demo@example.invalid" \
        commit -q -m "container build" && \
    python3 tools/lens/build_lens.py --repo . --out /srv/site

EXPOSE 8000
CMD ["python3", "-m", "http.server", "8000", "--directory", "/srv/site"]
