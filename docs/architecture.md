# Arkitektur for Agentbox 1.0

Agentbox kjører agentmiljøer i en egen rootless Docker-instans med eksplisitt
tilgang til prosjektmapper og utgående trafikk via Squid. Dette dokumentet
beskriver implementasjonen. Se [C1 og C2](architecture-c4.md) for diagrammer,
[implementasjonsvalg](decisions.md) for begrunnelser og
[teststatus](test-results.md) for verifikasjon og gjenstående arbeid.

## Eierskap og kontroll

Linux-brukeren `agentbox` eier daemon, images og containerdata. Hjemmet
`/var/lib/agentbox` er privat og monteres ikke inn i agentcontainerne.
Containerens hjem er `/home/agent` i dens skrivbare lag.

Utvikleren bruker en Python-CLI. En fast administratorinstallert hjelper
kjører som `agentbox` via en avgrenset sudo-regel og mottar JSON på stdin.
Kontrollkoden ligger under `/opt/agentbox`, innstillinger under `/etc/agentbox`,
og kontrolltilstand under `/var/lib/agentbox/state`. Utviklerens private
ACL-journal ligger separat i `/var/lib/agentbox-operator`.

Docker-operasjoner bruker fast socket `/run/user/<uid>/docker.sock` og
kontrollerer daemonidentitet og rootless-modus. Docker-socketen og kontrollfiler
eksponeres ikke for agenten. Andre Docker-instansers konfigurasjon endres ikke.

## Tilgang til prosjektmapper

Eksisterende prosjektmapper registreres og monteres direkte, uten flytting
eller kopiering. Ett miljø kan montere flere prosjekter som `rw` eller `ro`;
flere miljøer kan kjøre samtidig. Endringer i montert kode lagres på verten.

ACL-er gir tjenestebrukeren nødvendig traversering av foreldrekataloger og
tilgang til prosjektinnholdet. Foreldrene trenger ikke listetilgang.
Prosjektroten må eies av utvikleren. Overlappende registreringer, hardlenkede
filer og spesialfiler avvises; symlinker i innholdet og nestede mounts utelates
fra rekursiv ACL-behandling.

| På verten | I containeren |
| --- | --- |
| `/home/ok/src/pacman` | `/home/agent/src/pacman` |
| `/home/ok/project/pub-pc` | `/home/agent/project/pub-pc` |

Agentens UID 0 mappes til `agentbox` på verten. ACL-er tillater samarbeid med
utvikleren; restriktive filmoduser kan kreve eksplisitt reparasjon.
Reparasjon og tilbakekalling krever at alle berørte miljøer er stoppet.
Tilbakekalling sperrer tilgang gjennom prosjektroten uten å slette innhold,
endre eierskap eller fjerne innholdets ACL-er.

## Nettverk og images

Hvert miljø har en agent, en Squid-proxy, et lukket `isolated` bridge-nettverk
og et separat eksternt nettverk. Bare proxyen kobles til begge nettverk.
Agenten har ingen direkte internettrute eller publiserte porter; IPv6 er deaktivert.

Policyen avviser alt unntatt eksakte domene/port-par for HTTP på 80 og CONNECT
på 443. Kontrollsiden validerer navnenes adresser og fastlåser én offentlig
IPv4-adresse per navn. Proxyen har ingen ekstern DNS-fallback.
En systemd-adressevakt stopper miljøer ved endrede vertsadresser;
vakten er asynkron, og nettverksadministrasjon på verten er betrodd.

Codex-imaget og det separate testimaget bruker samme isolering. Andre
kompatible images velges i YAML. Images må støtte UID 0, `/bin/sh` og
`sleep infinity`; deklarerte `VOLUME`-mounts avvises.
Imagebygging og imagehenting skjer på den betrodde kontrollsiden.

## Livssyklus og sikkerhetsgrense

`stop` bevarer containerlaget, inkludert Codex-innlogging. Uendret konfigurasjon
kan startes igjen. Endret konfigurasjon eller vertsadresse krever `remove` og
ny `start`; hjem og innlogging slettes da, mens monterte prosjektfiler består.
Separat profilvolum og automatisk oppstart av miljøer etter vertsreboot er
ikke implementert.

Agenten kjører med droppede capabilities, `no-new-privileges`, ressursgrenser
og en strengere Moby-seccomp-profil som blant annet blokkerer nye Unix-sockets.
Dette begrenser kompatibilitet med verktøy som trenger slike sockets.

Mountene avgrenser normal filtilgang. Rootless-containerne deler vertens
kjerne. Ved utbrudd med tjenestebrukerens rettigheter gjelder all tilgang
`agentbox` har, inkludert andre registrerte prosjekter og allment lesbare filer.
Felles daemonbruker gir ikke separat vertsisolering mellom prosjektene.

## Avgrensninger og videre arbeid

Se [teststatus](test-results.md) for labprøver, manuell bruk og testavgrensninger.
Linked worktrees støttes ikke i versjon 1.0, inkludert tilgang
til delte Git-metadata utenfor arbeidsmappen. Separat profillagring er et
mulig senere valg.

Neste vurdering er sammenligning med OpenShell og Docker
Sandboxes: isoleringsgrenser, nettverkspolicy, mounts og rettigheter,
samtidige miljøer, imagevalg, plattformkrav og vedlikehold.

## Teknisk grunnlag

- [Rootless UID-mapping](https://docs.docker.com/engine/security/rootless/uid-gid-mapping/)
- [Docker gateway-moduser](https://docs.docker.com/engine/network/port-publishing/#gateway-modes)
- [Squid CONNECT og HTTPS](https://wiki.squid-cache.org/Features/HTTPS)
- [Git worktrees](https://git-scm.com/docs/git-worktree)
