# Bruk av Agentbox 1.0

Kjør kommandoene som utvikleren på verten. Agentbox velger sin egen rootless
Docker-instans; du trenger ikke bytte Docker-context eller sette `DOCKER_HOST`.
Se [installasjon](installation.md) hvis `doctor` ikke fungerer.

## Prosjekt og miljø

| Begrep | Eksempel | Betydning |
| --- | --- | --- |
| Prosjekt | `pubnix` | Registrert vertsmappe, eksempelvis `~/src/pubnix` |
| Miljø | `pubnix-codex` | Agentcontainer, proxy og nettverk med egen livssyklus |
| Miljøfil | `~/.config/agentbox/environments/pubnix-codex.yaml` | Valgt image, prosjektmonteringer og nettverkspolicy |

Ett miljø kan montere flere registrerte prosjekter. Samme prosjekt kan brukes
i flere miljøer, men alle med skrivetilgang arbeider på de samme filene.
Miljønavnet og prosjektets navn trenger ikke være like.

## Registrer en prosjektmappe

```sh
agentbox project add pubnix --path "$HOME/src/pubnix"
agentbox project list
agentbox project check pubnix
```

Registrering gir tjenestebrukeren tilgang til mappen. Prosjektroten må eies
av utvikleren. ACL-er gir begge brukerne tilgang til innholdet og standard-ACL
for nye filer. Foreldrekataloger får nødvendig traversering, uten listetilgang.

Andre brukeres effektive rettigheter bevares når ACL-masken utvides; tidligere
maskerte biter kan trimmes fra rå oppføringer. Overlappende registreringer,
hardlenkede filer, spesialfiler og ukjente eiere avvises. Symlinker i innholdet
følges ikke ved ACL-endring, og nestede mounts utelates.
Et mislykket oppsett markeres som uferdig; rett årsaken før reparasjon eller
tilbakekalling.

## Opprett miljøfilen

Legg miljøfilene utenfor mapper agenten kan skrive til, eksempelvis under
`~/.config/agentbox/environments/`. Ikke legg hemmeligheter i YAML-filen.

```yaml
name: pubnix-codex
image: agentbox-dev:local
workdir: /home/agent/src/pubnix
command: ["codex"]
mounts:
  - project: pubnix
    target: /home/agent/src/pubnix
    mode: rw
network:
  allow:
    - host: api.openai.com
      port: 443
resources:
  cpus: 2
  memory: 4g
  pids: 512
```

`mounts[].project` viser til prosjektregisteret. `target` er stien inne i
containeren; `workdir` må være denne stien eller en eksisterende undermappe.
Velg `mode: ro` for skrivebeskyttet montering. Legg til flere oppføringer for
flere prosjekter, med ulike mål som ikke overlapper.

Eksempelet tillater bare `api.openai.com:443`. Det er ingen komplett liste
for alle innloggingsmetoder eller Codex-funksjoner. Velg nødvendige
agentdestinasjoner eksplisitt. `network: {allow: []}` stenger ekstern tilgang.
Bruk `command: ["bash"]` for å åpne et vanlig skall mens du prøver filtilgang.

## Start, åpne og avslutt

```sh
agentbox validate "$HOME/.config/agentbox/environments/pubnix-codex.yaml"
agentbox start pubnix-codex --config "$HOME/.config/agentbox/environments/pubnix-codex.yaml"
agentbox shell pubnix-codex
```

Navnet etter `start` må være likt `name` i miljøfilen. `shell` kjører
`command` fra filen, som kan være Codex eller Bash. Du kan alltid åpne Bash
separat uten å endre konfigurasjonen:

```sh
agentbox exec pubnix-codex -- bash
```

Avslutt programmet eller skallet for å lukke terminalsesjonen. Miljøet
fortsetter å kjøre. Åpne det igjen med `agentbox shell pubnix-codex`.

```sh
agentbox status
agentbox stop pubnix-codex
```

Et stoppet miljø gjenopptas med samme `start`-kommando og miljøfil.
Miljøene startes ikke automatisk etter vertsreboot.

## Innlogging og verktøyoppsett

Logg inn i Codex inne i miljøet. For headless ChatGPT-innlogging beskriver
[OpenAI Docs](https://learn.chatgpt.com/docs/auth) `codex login --device-auth`:

```sh
agentbox exec pubnix-codex -- codex login --device-auth
```

Tillat innloggingsmetodens nødvendige destinasjoner først. Bruk
`cli_auth_credentials_store = "file"` i Codex-konfigurasjonen for eksplisitt
fillagring. Vertens keyring, personlige Codex-oppsett, miljøvariabler og
SSH-agent deles ikke automatisk inn.

API-nøkkel kan gis fra en privat fil på verten:

```sh
chmod 600 /sti/til/privat-nokkelfil
agentbox login-api-key pubnix-codex --key-file /sti/til/privat-nokkelfil
```

Hjelperen sender nøkkelen til `codex login --with-api-key` via stdin.
Nøkkelverdien gis ikke som argument eller miljøvariabel. Innloggingskoder,
tokens og nøkler skal ikke sjekkes inn eller deles i chat.

Verktøyoppsett, eksempelvis Codex sin `~/.codex/config.toml`, ligger i
containerens `/home/agent`. Eksterne HTTP-baserte MCP-tjenester trenger også
eksplisitt tillatelse for destinasjonen. Agentbox konfigurerer ikke disse
tjenestene eller deres tokens automatisk.

## Logger og endret nettverkspolicy

Fra en annen terminal på verten:

```sh
agentbox logs pubnix-codex
agentbox logs pubnix-codex --proxy
```

Proxyloggen viser destinasjon og resultat uten URL-sti eller query.
Agentutdata lagres i private, størrelsesbegrensede logger uten generell
innholdsfiltrering; utdata kan inneholde hemmeligheter.
`logs` viser et utsnitt, og følger ikke nye hendelser kontinuerlig.

Legg nødvendige eksakte navn og porter til under `network.allow`. Bare HTTP
på 80 og HTTPS via CONNECT på 443 støttes. Underdomener tillates ikke
automatisk. Imagebygging og imagehenting skjer på kontrollsiden og bruker
ikke denne listen.

**Endret policy krever fjerning og ny opprettelse. Det sletter hjem og innlogging.**
Monterte prosjektfiler beholdes. Bevar nødvendig verktøyoppsett separat før
fjerning, med hemmeligheter lagret privat utenfor kodeprosjektet.

```sh
agentbox remove pubnix-codex
agentbox start pubnix-codex --config "$HOME/.config/agentbox/environments/pubnix-codex.yaml"
```

## Hva beholdes?

| Handling | Prosjektfiler på verten | Containerens hjem, innlogging og installerte filer |
| --- | --- | --- |
| Avslutte terminalsesjonen | Beholdes | Beholdes; miljøet kjører videre |
| `stop` og `start` med uendret oppsett | Beholdes | Beholdes |
| Restart av Docker og manuell gjenopptak | Beholdes | Beholdes |
| `remove` og ny `start` | Beholdes | Slettes og opprettes på nytt |

Hvert miljø har egen innlogging; separat profilvolum finnes ikke i 1.0.
Endret konfigurasjon eller vertsadresse krever fjerning og ny opprettelse.
Fastlåste DNS-adresser beholdes ved gjenopptak. Ny navneoppløsning krever også
ny opprettelse. Prosjektregistreringer og ACL-er består til du tilbakekaller dem.

## Bytt prosjekt eller image

Registrer neste prosjekt, lag en egen miljøfil og start miljøet med et nytt
navn. Det eksisterende miljøet kan fortsette å kjøre. For et annet verktøy
mot samme prosjekt bruker du også et nytt miljønavn og velger image i YAML.

Andre kompatible images kan hentes med `agentbox pull-image IMAGE`. De må
være amd64 eller arm64, støtte UID 0 og ha `/bin/sh` og `sleep infinity`.
Images med deklarerte `VOLUME`-mounts avvises. Alle images bruker samme
nettverks- og syscallbegrensninger; se [arkitekturvalg](decisions.md).

## Reparer eller tilbakekall prosjekttilgang

Stopp alle miljøer som bruker prosjektet først, også de med read-only-mounts.
Velg deretter operasjonen du trenger:

```sh
agentbox project check pubnix
agentbox project repair pubnix
# Alternativt, for å avslutte delingen:
agentbox project revoke pubnix
```

`chmod` eller restriktivt opprettede filer kan kreve reparasjon.
Helt utilgjengelige katalogtrær eller andre eiere kan kreve manuell retting
fra fileieren før reparasjon kan fullføres.

Tilbakekalling legger en eksplisitt sperre for `agentbox` på prosjektroten.
Også agentbox-eide filer under roten blokkeres. Filer og eierskap beholdes,
og innholdets ACL-er blir liggende. Flytting til en ubeskyttet sti kan derfor
gi tilgang igjen. Foreldrenes administrerte ACL-er gjenopprettes når ingen
andre prosjekter trenger dem og ingen manuelle konflikter er oppdaget.

## Tab-completion i Bash

```sh
source <(agentbox completion bash)
```

Installeren legger inn completion for nye skall med `bash-completion` aktivert.
Tab foreslår kommandoer, flagg, eksisterende miljønavn og registrerte prosjekter.
Filstier fullføres etter `--config` og `--key-file`; kataloger etter `--path`.
Navneoppslag ber ikke om sudo-passord og avbrytes etter to sekunder.

## Vanlige feil

| Feil | Årsak og neste steg |
| --- | --- |
| `Environment is not running` | Prosjektregistrering starter ikke et miljø. Bruk `start NAVN --config FIL` før `shell` |
| `Working directory must be inside a mounted project` | Sett `workdir` lik `mounts[].target` eller en eksisterende undermappe |
| `Command name and configuration name disagree` | Bruk samme miljønavn i `start` og YAML-feltet `name` |
| `No two collision-free /28 subnets` | Velg et ledig adresseområde etter [installasjonsveiledningen](installation.md#velg-adresseområde) |
| `Host addresses changed` | Adressevakten har stoppet miljøet; fjerning og ny opprettelse kreves |
| Verktøy trenger Unix-sockets | Profilen blokkerer nye Unix-sockets. Velg kompatible verktøy; ikke svekk isoleringen automatisk |
