# This Dockerfile is for any service (release) defined in CI_TMPL_HELM_RELEASE_NAMES in .gitlab-ci.yml
# without it's own Dockerfile in a deploy/services/<service_name> folder

# args to use inside FROM directives
# # *_IMAGE ARGS will be used in later version of this template
# ARG PY_IMAGE
ARG PY_IMAGE_VERSION

# first stage
# by default uses alpine-based python image
FROM harbor.wildberries.ru/devops/ci/base-images/python:${PY_IMAGE_VERSION} AS requirements-cache

# install dependencies to the local user directory (eg. /root/.local)
WORKDIR /requirements
COPY requirements.txt .
RUN pip3 install --user --no-cache-dir -r requirements.txt

# second release stage
FROM harbor.wildberries.ru/devops/ci/base-images/python:${PY_IMAGE_VERSION}

# place all app releated files into /app direcotry
WORKDIR /app
COPY . .

# copy only the dependencies installation from the 1st stage image with non-root user as owner
# non-root user 'appuser' from group 'appgroup' is from DevSecOps base Python image
COPY --from=requirements-cache --chown=appuser:appgroup /root/.local /home/appuser/.local

# upgrade packages for runtime
RUN apt-get update --no-cache && \
    apt-get upgrade --no-cache

# update PATH environment variable
ENV PATH=/home/appuser/.local/bin:$PATH

# run container as non-root user
USER appuser

CMD [ "python3", "/app/main.py" ]
