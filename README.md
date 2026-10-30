# Agentbox

Rootless Docker-miljøer for kodeagenter, med direkte prosjektmontering,
ACL-er og eksplisitt tillatt nettverkstrafikk gjennom Squid. Første image
inneholder Codex CLI 0.166.0. Flere prosjekter og images kan brukes samtidig.

Implementasjonen testes i en disponibel Ubuntu-VM. Se
[teststatus](docs/test-results.md) før bruk og
[implementasjonsvalg](docs/decisions-mvp.md) for sikkerhetsgrenser.

## Oppsett

Referanseplattformen er Ubuntu 24.04 med systemd, cgroup v2, POSIX ACL,
user namespaces og rootless Docker. Docker 29.9.2 er testet. Installer
[Docker Engine og rootless extras](https://docs.docker.com/engine/security/rootless/)
før prosjektets installer kjøres. Andre nødvendige pakker på Ubuntu:

```sh
sudo apt-get install acl uidmap dbus-user-session slirp4netns python3-venv sudo iproute2
sudo scripts/install.sh --operator "$(id -un)"
agentbox doctor
agentbox build-images
```

Installeren oppretter `agentbox` med hjem `/var/lib/agentbox`, installerer
kontrollkode under `/opt/agentbox` og gir den valgte utvikleren tilgang til
en fast kontrollhjelper gjennom sudo. Den installerer en privat Python-venv
med PyYAML 6.0.2 og trenger pakketilgang ved første oppsett.

Docker-pakker installeres ikke av prosjektinstalleren. Andre Docker-instansers
konfigurasjon og context endres ikke. CPU-/minne-/prosesskontroll delegeres til
den konkrete systemd-brukerinstansen for `agentbox`.
Stopp miljøene før reinstallasjon eller oppdatering av kontrollverktøyet.

## Registrer eksisterende prosjekter

```sh
agentbox project add pacman --path "$HOME/src/pacman"
agentbox project add pub-pc --path "$HOME/project/pub-pc"
agentbox project list
```

Prosjektroten må eies av utvikleren. Registrering gir begge brukerne `rwX`
på prosjektinnholdet, med standard-ACL for nye filer. Foreldrekataloger får
bare nødvendig traversering for `agentbox`. Andre brukeres effektive
rettigheter skal bevares når ACL-masken utvides; maskerte, inaktive biter
kan derfor trimmes i ACL-en.

MVP-en avviser overlappende prosjektregistreringer, hardlenkede filer,
spesialfiler og ukjente eiere. Symlinker i innholdet følges ikke ved ACL-endring.
Nestede mounts utelates. Et mislykket oppsett markeres som uferdig; bruk
`project repair` etter at årsaken er rettet, eller tilbakekall tilgangen.

## Konfigurer og bruk et miljø

Lag en YAML-fil uten hemmeligheter, for eksempel:

```yaml
name: pacman-dev
image: agentbox-dev:local
workdir: /home/agent/src/pacman
command: ["codex"]
mounts:
  - project: pacman
    target: /home/agent/src/pacman
    mode: rw
  - project: pub-pc
    target: /home/agent/project/pub-pc
    mode: ro
network:
  allow:
    - host: api.openai.com
      port: 443
resources:
  cpus: 2
  memory: 4g
  pids: 512
```

Eksempelet tillater bare `api.openai.com:443`. Velg innloggingsmetode og
legg til dens konkrete destinasjoner eksplisitt. ChatGPT-innlogging kan kreve
andre destinasjoner enn API-nøkkelinnlogging; eksempelet er ingen komplett
liste for alle Codex-funksjoner. Ingen underdomener tillates automatisk.

```sh
agentbox validate pacman-dev.yaml
agentbox start pacman-dev --config pacman-dev.yaml
agentbox shell pacman-dev
agentbox exec pacman-dev -- bash
agentbox status
agentbox logs pacman-dev
agentbox logs pacman-dev --proxy
agentbox stop pacman-dev
```

`shell` kjører konfigurasjonens kommando, i dette eksempelet Codex. `exec`
kan kjøre et skall eller en annen kommando. Terminalsesjoner og miljøets
levetid er separate. Et nytt miljø med annet navn kan kjøres samtidig.

Uendret konfigurasjon kan startes igjen etter `stop`; containerens hjem,
innlogging og installerte filer bevares. Endret konfigurasjon eller vertsadresse
krever eksplisitt `remove` og ny `start`. Det sletter containerens skrivbare
lag, inkludert innlogging; montert kode blir liggende.

Andre kompatible 64-bits images kan hentes med `agentbox pull-image IMAGE` og
velges i YAML. De må ha `/bin/sh` og `sleep infinity` og støtte UID 0.
Images med implisitte `VOLUME`-mounts avvises. De samme nettverks- og
syscallbegrensningene gjelder alle images.

## Innlogging og hemmeligheter

Logg inn eksplisitt inne i miljøet. For headless ChatGPT-innlogging beskriver
[OpenAI Docs](https://learn.chatgpt.com/docs/auth) `codex login --device-auth`.
Kjør dette med `agentbox exec pacman-dev -- codex login --device-auth` i en
terminal, med nødvendige destinasjoner tillatt. Innloggingskoder og tokens
skal ikke deles i chat eller sjekkes inn.
Bruk `cli_auth_credentials_store = "file"` i Codex-konfigurasjonen dersom
credential-lagring skal velges eksplisitt; vertens keyring deles ikke inn.

API-nøkkel kan alternativt gis fra en privat fil uten nøkkelverdi på kommandolinjen:

```sh
chmod 600 /sti/til/privat-nokkelfil
agentbox login-api-key pacman-dev --key-file /sti/til/privat-nokkelfil
```

Kontrollhjelperen sender nøkkelen til `codex login --with-api-key` via stdin.
Vertens miljøvariabler, personlige Codex-oppsett og SSH-agent deles ikke automatisk.
Prosjektfiler som `.env` er tilgjengelige hvis de ligger i et valgt mount.

Agentens stdout/stderr kan selv inneholde hemmeligheter. Disse loggene er
private og størrelsesbegrensede, men har ingen generell innholdsfiltrering.
Proxyloggen inneholder destinasjon og resultat, uten URL-sti eller query.

## Reparasjon og tilbakekalling

Stopp alle miljøer som bruker prosjektet, også miljøer med read-only-mounts:

```sh
agentbox project repair pacman
agentbox project revoke pacman
```

Tilbakekalling legger en eksplisitt sperre for `agentbox` på den utviklereide
prosjektroten. Det blokkerer også tilgang til agentbox-eide filer under roten.
Filene slettes ikke og får ikke ny eier. ACL-er på innholdet beholdes; ikke
flytt innholdet til en ubeskyttet sti og forvent at rotsperren følger med.
Foreldrekatalogers administrerte ACL-er gjenopprettes når andre registreringer
ikke trenger dem, så lenge det ikke er oppdaget manuelle konflikter.

`chmod` og restriktivt opprettede filer kan gjøre ACL-reparasjon nødvendig.
Helt utilgjengelige katalogtrær eller andre eiere kan kreve en manuell
rettighetsretting fra fileieren før reparasjon kan fullføres.

## Utvikling og verifikasjon

```sh
uv sync --extra dev --locked
uv run --locked pytest
uv run --locked ruff check src tests scripts/lab
uv run --locked ruff format --check src tests scripts/lab
```

Den disponible KVM-laben krever QEMU, `qemu-img`, `xorriso`, curl og SSH.
Labkommandoene nedenfor skal kjøres utenfor en agentsandkasse som sperrer KVM:

```sh
scripts/lab/vm.sh prepare
scripts/lab/vm.sh start
scripts/lab/vm.sh ssh
scripts/lab/vm.sh stop
```

Bootstrap- og nettverksprøver har en eksplisitt `agentbox-lab`-vertskontroll.
Reproduksjon av testløpet er beskrevet i [teststatus](docs/test-results.md).
Koden kopieres inn med tar/SSH; vertens mapper deles ikke inn i VM-en.

## Stopp og avinstallasjon

Bruk `agentbox remove NAVN` og tilbakekall prosjekter før avinstallasjon.
Stopp deretter Docker-brukertjenesten og `agentbox-watch.service` for den
konkrete tjenestebrukeren. Fjern prosjektets sudo-regel, entrypoints og
`/opt/agentbox` først når miljøene er avviklet.

Ikke slett `agentbox`-brukeren, hjemmet eller journalen under
`/var/lib/agentbox-operator` automatisk: brukeren kan fortsatt eie prosjektfiler,
og journalen kan være nødvendig for å rydde ACL-er. MVP-en har ingen automatisk
brukersletting eller destruktiv fullavinstallasjon.
