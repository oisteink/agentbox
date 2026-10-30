# Independent image used to verify that the runtime is not coupled to Codex.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive HOME=/home/agent
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl git python3 iproute2 dnsutils \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /home/agent
WORKDIR /home/agent
CMD ["bash"]
