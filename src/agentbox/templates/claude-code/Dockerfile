FROM node:22-bookworm-slim AS installer
ARG CLAUDE_CODE_VERSION=2.1.316
RUN npm install --global @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive HOME=/home/agent
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl git python3 iproute2 dnsutils \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /home/agent
COPY --from=installer /usr/local/ /usr/local/
ENV DISABLE_AUTOUPDATER=1
RUN claude --version
WORKDIR /home/agent
CMD ["bash"]
