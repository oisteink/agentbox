FROM node:22-bookworm-slim AS installer
ARG OPENCODE_VERSION=1.19.5
RUN npm install --global opencode-ai@${OPENCODE_VERSION}

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive HOME=/home/agent
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl git python3 iproute2 dnsutils \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /home/agent
COPY --from=installer /usr/local/ /usr/local/
ENV NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
RUN opencode --version
WORKDIR /home/agent
CMD ["bash"]
