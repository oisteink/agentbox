FROM golang:1.27.3-bookworm AS build
WORKDIR /build
RUN go install golang.org/x/vuln/cmd/govulncheck@v1.9.0
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN go test ./... && go vet ./... && govulncheck ./... \
    && CGO_ENABLED=0 go build -trimpath -o /agentbox-proxy .

FROM debian:13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 proxy-agentbox \
    && useradd --uid 10001 --gid 10001 --no-create-home proxy-agentbox
COPY --from=build /agentbox-proxy /usr/local/bin/agentbox-proxy
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/agentbox-proxy"]
CMD ["serve"]
