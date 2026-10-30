# Teststatus for Agentbox 1.0.1

Dato: 30. oktober 2026. Implementasjonen er kjørt i en disponibel KVM-VM med
egne brukere og midlertidige prosjektmapper. Ingen personlige prosjektmapper
er delt inn i VM-en. Installasjon og manuell Codex-bruk er deretter prøvd på
utviklerens Debian-vert. Utvikleren godkjente Agentbox 1.0 samme dag.

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

## Opprinnelige kontroller for 1.0

- Lokal testpakke ved versjon 1.0: **64 bestått**, inkludert terminal- og completion-tester.
- Opprinnelig VM-prøve: **49 bestått** (48 enhetstester og installert CLI-integrasjon).
  VM-prøven er ikke kjørt på nytt etter terminal- og completion-rettelsene.
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

Testpakken og labprøvene undersøker områdene i A1–A13 på referanseplattformen.
Resultatene over beskriver de konkrete kontrollene; de innebærer ikke at alle
varianter i akseptansekriteriene er uttømmende verifisert. Følgende områder
har fortsatt begrenset testdekning:

- Bredere prøver av samtidige manuelle ACL-endringer, vertsreboot og krasj
  midt i hver enkelt oppstartsoperasjon.
- Andre distribusjoner enn labens Ubuntu og den manuelt prøvde Debian-verten,
  arm64, andre agentsystemer og annen Docker/Squid-versjon.

Adressevakten er asynkron og deler lås med kontrolloperasjoner. Nettverksendringer
på verten behandles som betrodd administrasjon; testen viser stopp etter
oppdaget endring, ikke atomisk sperring i endringsøyeblikket.

## Manuell utprøving på Debian-verten

Utvikleren installerte tjenestebruker, rootless Docker og kontrollverktøy,
bygget images og registrerte et eksisterende prosjekt. `doctor` bekreftet
rootless Docker 29.9.2 med systemd-cgroups. Utvikleren bekreftet fungerende
Codex-terminal etter retting av terminalstørrelsen, og godkjente deretter versjon 1.0.

To problemer fra utprøvingen er rettet:

- Standardområdet `172.28.0.0/16` kolliderte med et eksisterende Docker-nettverk.
  Et ledig område ble valgt i vertsinnstillingene. Installeren bevarer nå valget,
  og feilmeldingen forklarer hvor adresseområdet konfigureres.
- Terminalen rapporterte `0 × 0` til Codex. En pseudoterminal bevarer nå størrelse
  og videresender størrelsesendringer mens agentutdata fortsatt logges.
  En separat prøve mot den installerte CLI-en bekreftet `30 × 100`.

Bash-completion er også installert og kontrollert mot vertens faktiske miljø-
og prosjektnavn. Context7 ble diskutert som ønsket integrasjon; den er ikke
verifisert som del av denne leveransen. Ingen personlige tokens inngår i testbevisene.

## Verifikasjon av 1.0.1

| Kontroll | Resultat |
| --- | --- |
| Lokale enhetstester | 92 bestått |
| VM: enhetstester og livssyklus gjennom installert CLI | 93 bestått |
| Ruff og Bash-syntaks | Bestått |
| Codex uten delt bakgrunnsserver | To terminaloppstarter viste grensesnittet; ChatGPT-innlogging besto |
| Kortnavn og completion | Kontrollert med installert CLI og midlertidig konfigurasjonskatalog |
| Installering uten `--operator` | Gjennomført i VM; bruker valgt fra `SUDO_USER` |
| Frittstående avinstallasjon | Bestått rett etter ren installasjon og med kjørende miljø, aktive og tilbakekalte prosjekter |

Codex-prøven sendte ingen oppgave til modellen. Den omgår feilen ved å kjøre
med `--no-daemon`; det konkrete systemkallet som blokkerer den delte serveren
er ikke kartlagt.

Startkommandoen bruker nå én fil eller et lagret kortnavn. Tester dekker
filnavn som avviker fra miljønavnet, manglende filer, `.yaml`/`.yml`,
`XDG_CONFIG_HOME`, tvetydige kortnavn og lokale filer som ikke skal overstyre
en lagret konfigurasjon. Completion leser ikke YAML-innhold og ber ikke om sudo.

Avinstallasjonsprøven besto separat i den disponible VM-en. Den stoppet et
kjørende miljø, overførte agentbox-eide filer fra aktive og tilbakekalte
prosjekter, bevarte manuelle ACL-endringer og kontrollerte symlinker og
nestede mounts. Prøven bekreftet også sletting av bruker, tjenester og data,
samt at den eksisterende rootful Docker-instansen beholdt daemon-ID-en.

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
