FROM node:22-bookworm-slim AS codex
ARG CODEX_VERSION=0.166.0
RUN npm install --global @openai/codex@${CODEX_VERSION}

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive HOME=/home/agent
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl git python3 iproute2 dnsutils \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /home/agent
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules/@openai /usr/local/lib/node_modules/@openai
RUN ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && codex --version \
    && rm -rf /home/agent/.codex
WORKDIR /home/agent
CMD ["bash"]
