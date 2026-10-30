# Teststatus for MVP

Dato: 30. oktober 2026. Implementasjonen er kjørt i en disponibel KVM-VM med
egne brukere og midlertidige prosjektmapper. Ingen personlige prosjektmapper
er delt inn i VM-en. Installasjon på utviklerens hovedmaskin og manuell
Codex-innlogging med en reell oppgave gjenstår før full MVP-godkjenning.

## Referansemiljø

| Del | Testet versjon |
| --- | --- |
| VM | Ubuntu 24.04.5 LTS, amd64, kernel 6.8.0-147-generic |
| Docker Engine og CLI | 29.9.2 |
| RootlessKit / slirp4netns | 3.3.0 / 1.2.1 |
| containerd / runc | 2.4.2 / 1.5.2 |
| Squid | 6.14 |
| Codex CLI | 0.166.0 |
| Kontrollverktøy | Python 3.12, privat venv med PyYAML 6.0.2 |
| Lokal utvikling | Python 3.13.16, avhengigheter fra `uv.lock` |

Rootful og rootless Docker kjørte samtidig i VM-en, med ulike daemon-ID-er.
`agentbox doctor` fortsatte å velge rootless-instansen med både `DOCKER_HOST`
og `DOCKER_CONTEXT` satt til den andre instansen.

## Gjennomførte kontroller

- Lokal testpakke: **48 bestått**.
- VM: enhetstester og installert CLI-integrasjon: **49 bestått**.
- Ruff lint og formatteringskontroll: bestått.
- Bash-syntakskontroll for installasjon og labskript: bestått.
- Teknisk grunnprøve og kontrollert HTTP-/HTTPS-/DNS-prøve: bestått.

Integrasjonstesten kjører gjennom den installerte sudo-hjelperen, ikke en
mock av Docker. Den dekker to forskjellige images, to samtidige miljøer,
terminaltilgang, Codex-versjon, flere mounts, read-only, skjulte søskenmapper,
kodeendringer fra begge brukerne, reparasjon etter `chmod 0600`, gjenopptak,
private logger, nettverksskille og tilbakekalling.
En kontrollert restart av rootless Docker bekrefter at adressevakten starter
igjen og at gjenopptak bevarer containerens skrivbare lag.

Nettverksprøven bruker en separat Linux-nettverksnamespace som kontrollert
ekstern tjeneste. En syntetisk offentlig adresse er routet dit inne i VM-en;
ingen produksjonsregel åpnes for private adresser. HTTPS bruker et eget
testsertifikat som klienten eksplisitt stoler på. Kontrollklienter bekrefter
at tjenestene faktisk svarer før blokkering godtas som resultat.

| Område | Observert resultat |
| --- | --- |
| UID-mapping | Container-UID 0 oppretter filer som tjenestebrukeren på verten |
| Samarbeid | Utvikleren og agenten kan redigere nye filer; `0600` diagnostiseres og repareres |
| Tilbakekalling | Navngitt sperre på utviklereid rot blokkerer også agentbox-eide filer |
| Unix-sockets | Standardprofilen slipper gjennom en mountet vertssocket; agentprofilen blokkerer socket-opprettelsen |
| Prosesskommunikasjon | Stream-socketpar og Python asyncio fungerer med agentprofilen |
| Ressurser | `cpu.max`, `memory.max` og `pids.max` matcher konfigurasjonen; en 12-prosessgrense stopper fork etter 11 barn |
| Direkte nettverk | Agentnettverket mangler rute til det fungerende eksterne kontrollendepunktet og vertstjenesten |
| Miljøskille | En tjeneste som svarer inne i miljø B, kan ikke nås fra miljø A |
| DNS | Ingen eksterne spørringer observert fra intern Docker-resolver; ekstern kontrollklient når samme DNS-tjeneste |
| Proxy | Tillatt HTTP og HTTPS virker; feil domene/port-par, subdomener, IP-litteraler og interne adresser avvises |
| DNS-endring | Endring til loopback etter oppstart endrer ikke den fastlåste proxy-destinasjonen |
| Proxybortfall | Den installerte CLI-ens nettverkstilgang feiler når dens proxy stoppes |
| Adresseendring | Adressevakten stopper agent og proxy ved endret vertsadresseoversikt |
| Proxylogg | Destinasjonen vises; testens private URL-query finnes ikke i tilgangsloggen |

## Avgrensning mot akseptansekriteriene

A1–A13 er dekket av testpakke og labprøver på referanseplattformen.
Dette er ikke en generell sikkerhetssertifisering eller uttømmende
feilinjektionstest av alle kombinasjoner. Følgende gjenstår eksplisitt:

- Manuell Codex-innlogging og en faktisk kodeoppgave med brukerens konto.
  Ingen personlige tokens er hentet og ingen modellforespørsel er sendt.
- Manuell vurdering av brukerens konkrete nettverk, prosjektmapper og ønskede
  agentdestinasjoner før installasjon på hovedmaskinen.
- Bredere prøver av samtidige manuelle ACL-endringer, vertsreboot og krasj
  midt i hver enkelt oppstartsoperasjon.
- Andre distribusjoner, arm64, andre agentsystemer og annen Docker/Squid-versjon.

Adressevakten er asynkron og deler lås med kontrolloperasjoner. Nettverksendringer
på verten behandles som betrodd administrasjon; testen viser stopp etter
oppdaget endring, ikke atomisk sperring i endringsøyeblikket.

## Reproduser laben

Kjør fra repoet på en vert med KVM, QEMU og nødvendige labverktøy:

```sh
scripts/lab/vm.sh prepare
scripts/lab/vm.sh start
scripts/lab/vm.sh ssh 'cloud-init status --wait'
scripts/lab/vm.sh ssh sudo bash -s < scripts/lab/bootstrap.sh
tar --exclude=.git --exclude=.lab --exclude=.venv --exclude=__pycache__ \
  --exclude=.aws --exclude=.codex --exclude=.agents -cf - . | \
  scripts/lab/vm.sh ssh 'mkdir -p /home/developer/agentbox-src && tar -xf - -C /home/developer/agentbox-src'
scripts/lab/vm.sh ssh 'bash /home/developer/agentbox-src/scripts/lab/build-images.sh'
scripts/lab/vm.sh ssh 'sudo bash /home/developer/agentbox-src/scripts/install.sh --operator developer'
scripts/lab/vm.sh ssh 'agentbox build-images'
python3 src/agentbox/seccomp.py > .lab/socket-profile.json
scripts/lab/vm.sh ssh 'sudo tee /var/lib/agentbox/lab-socket-profile.json >/dev/null' < .lab/socket-profile.json
scripts/lab/vm.sh ssh sudo python3 - < scripts/lab/probe.py > .lab/probe.json
scripts/lab/vm.sh ssh 'cd /home/developer/agentbox-src && AGENTBOX_LAB=1 python3 -m pytest -q tests/unit tests/integration/test_lifecycle.py'
scripts/lab/vm.sh ssh 'sudo python3 /home/developer/agentbox-src/scripts/lab/proxy_probe.py' > .lab/proxy-probe.json
scripts/lab/vm.sh stop
```

Vent til SSH svarer etter oppstart. Kjør nettverksprøven og livssyklustesten
sekvensielt: nettverksprøven endrer VM-adresser for å teste adressevakten.
Bootstrappen er avgrenset til verten `agentbox-lab`. `.lab/` inneholder
VM-disk, SSH-nøkkel og lokale logger og er utelatt fra Git.

Et [sanert resultatutdrag](evidence/lab-2026-10-30.json) følger repoet.
