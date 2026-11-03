# Arkitektur for Agentbox

Agentbox kjører agentmiljøer i en egen rootless Docker-instans med eksplisitt
tilgang til prosjektmapper og utgående trafikk via Go-proxyen. Dette dokumentet
beskriver implementasjonen. Se [C1 og C2](architecture-c4.md) for diagrammer,
[implementasjonsvalg](decisions.md) for begrunnelser og
[teststatus](test-results.md) for verifikasjon og gjenstående arbeid.

## Eierskap og kontroll

Linux-brukeren `agentbox` eier daemon, images og containerdata. Hjemmet
`/var/lib/agentbox` er privat og monteres ikke inn i agentcontainerne.
Containerens hjem er `/home/agent` i dens skrivbare lag.

Utvikleren bruker Python-CLI-en `abx`. En fast administratorinstallert hjelper
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
| `/home/developer/projects/project-a` | `/workspace/project-a` |
| `/home/developer/projects/project-b` | `/workspace/project-b` |

Agentens UID 0 mappes til `agentbox` på verten. ACL-er tillater samarbeid med
utvikleren; restriktive filmoduser kan kreve eksplisitt reparasjon.
Reparasjon og tilbakekalling krever at alle berørte miljøer er stoppet.
Tilbakekalling sperrer tilgang gjennom prosjektroten uten å slette innhold,
endre eierskap eller fjerne innholdets ACL-er.

## Nettverk og images

Hvert miljø har en agent, en Go-proxy, et lukket `isolated` bridge-nettverk
og et separat eksternt nettverk. Bare proxyen kobles til begge nettverk.
Agenten har ingen direkte internettrute eller publiserte porter; IPv6 er deaktivert.

Policyen avviser alt unntatt eksakte domene/port-par for HTTP på 80 og CONNECT
på 443. Kontrollsiden validerer navnenes adresser og fastlåser én offentlig
IPv4-adresse per navn. Proxyen har ingen ekstern DNS-fallback.
En systemd-adressevakt stopper miljøer ved endrede vertsadresser;
vakten er asynkron, og nettverksadministrasjon på verten er betrodd.

Agentimages bygges fra lokale Dockerfiles under `~/.config/agentbox/images/`
og velges med oppskriftsnavn i YAML. Alle kompatible agentimages bruker
samme isolering. Images må støtte UID 0, `/bin/sh` og
`sleep infinity`; deklarerte `VOLUME`-mounts avvises.
Byggkonteksten overføres fra CLI-en som tar etter en JSON-header og pakkes ut
i en privat midlertidig katalog med datafilter. Docker bygger katalogen og
behandler .dockerignore. Bygging og henting av baseimages skjer på den
betrodde kontrollsiden. Installeren bygger proxyimaget når det mangler;
ombygging gjøres med `proxy build`.
Bygg og fjerning sperres ved containere med samme eksakte image-ID,
også stoppede. Se [imagevalgene](decisions.md#lokale-imageoppskrifter).

## Livssyklus og sikkerhetsgrense

`scripts/uninstall.sh` kjøres fra repoet som administrator. Det stopper tjenestebrukerens
prosesser, overfører eierskap i registrerte prosjekter og fjerner installasjonen.
Skriptet bruker systemets Python uavhengig av den installerte CLI-en.
Vanlige kontrolloperasjoner får ikke denne root-tilgangen. Se
[avinstallasjon](installation.md#avinstallasjon) for omfang og filrydding.

`stop` bevarer containerlaget, inkludert verktøyoppsett og innlogging.
Uendret konfigurasjon kan startes igjen. Nettverk/tokenregler aktiveres med `proxy apply` uten å
slette hjemmet. Endret agentprofil eller vertsadresse krever `remove` og ny
`start`; hjem og innlogging slettes da, mens monterte prosjektfiler består.
Separat profilvolum og automatisk oppstart av miljøer etter vertsreboot er
ikke implementert.

Agenten kjører med droppede capabilities, `no-new-privileges`, ressursgrenser
og en strengere Moby-seccomp-profil som blant annet blokkerer nye Unix-sockets.
Dette begrenser kompatibilitet med verktøy som trenger slike sockets.

Mountene avgrenser normal filtilgang. Rootless-containerne deler vertens
kjerne. Ved utbrudd med tjenestebrukerens rettigheter gjelder all tilgang
`agentbox` har, inkludert andre registrerte prosjekter og allment lesbare filer.
Felles daemonbruker gir ikke separat vertsisolering mellom prosjektene.

## Avgrensninger

Se [teststatus](test-results.md) for labprøver, manuell bruk og testavgrensninger.
Linked worktrees med Git-metadata utenfor arbeidsmappen og separat
profillagring støttes ikke.

## Teknisk grunnlag

- [Rootless UID-mapping](https://docs.docker.com/engine/security/rootless/uid-gid-mapping/)
- [Docker gateway-moduser](https://docs.docker.com/engine/network/port-publishing/#gateway-modes)
- [goproxy](https://github.com/elazarl/goproxy)
- [Git worktrees](https://git-scm.com/docs/git-worktree)

## Genererte tokenplassholdere

[Tokenflyt som sekvensdiagram](architecture-c4.md#sekvens-fra-miljøvariabel-til-ekte-api-nøkkel).

Ved opprettelse lager kontrollhjelperen én tilfeldig plassholder per referert
klientvariabel med en ikke-tom kilde. `env: klient=kilde` skiller navnet i
agenten fra navnet som leses på verten; kortformen bruker samme navn. Ved
ny opprettelse med tom/manglende kilde settes klientvariabelen eksplisitt tom. Kartet lagres uten ekte nøkler i miljøtilstanden og inngår
i proxyens policyformat 3. Tom plassholder betyr deaktivert nøkkelregel;
regelen beholder TLS-avlytting og gir ingen nøkkelinnsetting. Bare proxyen får de ekte verdiene.

Proxyen erstatter en hel plassholder eller Bearer-formen når destinasjon og
header er autorisert. Andre verdier utløser ingen innsetting. Proxybytte og
nøkkelrotasjon beholder kartet. Nye variabelnavn krever eksplisitt gjenskaping,
fordi agentcontainerens miljø er fast. Tom/ikke-tom overgang krever også
gjenskaping; gammel proxy fjernes før denne overgangen avvises. Ingen egen shell-/exec-mekanisme
oppdaterer variablene i bakgrunnen.

Interne `AGENTBOX_TOKEN_<n>` beregnes etter sorterte klientnavn både ved
policygenerering og tokenoverføring. Tomme klientvariabler opptar fortsatt
sin indeks, men får ingen ekte verdi i proxyens miljø. Dette holder aliaser
og delt kilde entydige selv når kildenavnene har en annen sorteringsrekkefølge.

## Tillitsgrenser for API-nøkler

Konfigurasjonen autoriserer lesing av operatørens navngitte miljøvariabler.
En agent som kan endre YAML-filen, kan forsøke å dele andre vertsvariabler.
Hold derfor miljøfiler utenfor agentens skrivbare mounts og les credentials
før start/apply. Proxyen monterer ikke prosjekter eller Docker-socket.

Agenten får bare offentlig CA/bundle. Privat CA og ekte tokens tilhører den
betrodde kontroll-/proxysiden. Original CA-nøkkel ligger privat; read-only
snapshots for proxyen er beskyttet av vertskatalogens tilgangsrettigheter.
Tokenverdier lagres ikke i Agentbox-filer, men finnes i proxyens prosessmiljø
og Docker-metadata. Et fullstendig utbrudd til tjenestebrukeren kan avsløre dem.

En godkjent upstream kan reflektere en ekte nøkkel i responsen. Responsen
skannes ikke etter hemmeligheter. Tunnelerte CDN-domener kan tillate domain
fronting; en tillatt tjeneste er del av tillitsvurderingen. Plassholdere som
videresendes i URL/body eller vanlige tunneler gir ingen tilgang utenfor
miljøets proxy. Verktøyenes egne innloggingsdata og hemmeligheter i prosjektfiler
omfattes ikke av denne nøkkelskjermingen.
