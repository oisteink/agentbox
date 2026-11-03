# Agentbox

Agentbox lar deg kjøre kodeagenter mot utvalgte prosjektmapper på Linux.
Du beholder filene i editoren din, mens agenten arbeider i en container og
bare får utgående nettverkstilgang til destinasjoner du har tillatt.
Flere prosjekter, miljøer og kompatible images kan brukes samtidig.

En egen vertsbruker, `agentbox`, kjører Docker uten root-rettigheter.
Prosjektmapper deles med filrettigheter (ACL-er) og eksplisitte monteringer.
En Go-proxy håndhever tillatte destinasjoner og kan erstatte ufarlige
plassholdere med API-nøkler. Den ekte nøkkelen ligger bare på den betrodde
siden; agenten får en generert verdi i klientens miljøvariabel.
Det medfølgende utviklingsimaget inneholder Codex CLI 0.166.0.

![Agentbox, utvikleren og eksterne tjenester](docs/diagrams/agentbox-context.svg)

[C4-arkitekturen](docs/architecture-c4.md) forklarer systemkonteksten og de
kjørbare delene. Containerne deler vertens kjerne. Et utbrudd med `agentbox`
sine rettigheter kan nå alle prosjekter brukeren har fått tilgang til.

## Kom i gang

Installer først Docker Engine med rootless-støtte og prosjektets
forutsetninger etter [installasjonsveiledningen](docs/installation.md).
Kjør deretter fra repoet:

```sh
sudo scripts/install.sh
abx doctor
abx image new codex --template codex
abx image build codex
source <(abx completion bash)
```

Registrer et prosjekt som allerede finnes:

```sh
abx project add example --path "$HOME/src/example"
mkdir -p "$HOME/.config/agentbox/environments"
```

Et prosjekt er en vertsmappe med tildelt tilgang. Et miljø er en navngitt
container med valgt image, mounts og nettverkspolicy. Registrering av en
mappe oppretter ikke et miljø.

Lagre dette som `~/.config/agentbox/environments/example-codex.yaml`, utenfor
mappene agenten kan redigere:

```yaml
name: example-codex
image: codex
workdir: /home/agent/src/example
command: ["bash"]
mounts:
  - project: example
    target: /home/agent/src/example
    mode: rw
network:
  allow: []
```

Start og åpne miljøet:

```sh
abx validate example-codex
abx start example-codex
abx shell example-codex
```

Kortnavnet finner `example-codex.yaml` i `~/.config/agentbox/environments/`.
Du kan også bruke en eksplisitt YAML-sti, som `abx start ./agentbox.yaml`.

Dette åpner Bash i prosjektmappen med nettverket stengt. Endringer i montert
kode lagres direkte på verten. Miljønavnet beskriver planlagt Codex-bruk;
start med Bash for å kontrollere filtilgang. Følg
[bruksveiledningen](docs/usage.md) for nettverk, Codex-innlogging og daglig bruk.

`exit` lukker skallet. `abx stop example-codex` stopper miljøet og beholder
hjem og innlogging. `abx remove example-codex` sletter containerlaget,
inkludert innlogging og verktøyoppsett. Monterte prosjektfiler beholdes.

## API-nøkler via proxyen

`credentials[].env` kobler klientens variabel til en kilde på verten:

```yaml
credentials:
  - host: mcp.context7.com
    port: 443
    header: Authorization
    env: CONTEXT7_TOKEN=context7_api_key
```

Dette leser vertens `context7_api_key` og gir agenten `CONTEXT7_TOKEN` med en
unik plassholder. Klienten bruker denne som en vanlig nøkkel; proxyen bytter
den til den ekte verdien i riktig header mot `mcp.context7.com:443`.
`env: CONTEXT7_TOKEN` er kortform for `CONTEXT7_TOKEN=CONTEXT7_TOKEN`.
En manglende eller tom kilde gir en tom klientvariabel ved ny opprettelse.

Bruk [context7-codex.yaml](environments/context7-codex.yaml) som komplett
miljøfil. Kopier den til `~/.config/agentbox/environments/`. Filen bruker
prosjektet `example` som ble registrert over; tilpass `mounts[].project` hvis
du bruker et annet navn. Nettverkstillatelsene og aliaset er allerede lagt inn.

```sh
# På verten: rå nøkkel uten Bearer-prefiks, lest uten shellhistorikk.
read -rsp 'Context7 API-nøkkel: ' context7_api_key
printf '\n'
export context7_api_key
abx start context7-codex
abx exec context7-codex -- codex mcp add context7 \
  --url https://mcp.context7.com/mcp --bearer-token-env-var CONTEXT7_TOKEN
abx shell context7-codex
```

Codex sin egen kontoinnlogging gjøres separat med
[device-login](docs/usage.md#innlogging-og-verktøyoppsett). Etter endring av en
ikke-tom nøkkel brukes `abx proxy apply context7-codex`. Nye klientnavn
og tom/ikke-tom overgang krever gjenskaping; `remove` sletter hjem og innlogging.
Se [brukerveiledningen](docs/usage.md#api-tokens-i-proxyen) for tilbakekalling
og begrensninger.

## Dokumentasjon

| Dokument | Bruk det til |
| --- | --- |
| [Installasjon](docs/installation.md) | Forutsetninger, oppsett, adresseområde og avinstallasjon |
| [Bruk](docs/usage.md) | Prosjekter, miljøfiler, nettverk, innlogging og feilsøking |
| [C4-diagrammer](docs/architecture-c4.md) | Forstå omgivelsene og programmene som utgjør Agentbox |
| [Arkitektur](docs/architecture.md) | Eierskap, kontroll, filtilgang og sikkerhetsgrenser |
| [Spesifikasjon](docs/specification.md) | Produktkontrakten for Agentbox |
| [Arkitekturvalg](docs/decisions.md) | Begrunnelser og konsekvenser av isoleringsmekanismene |
| [Utvikling](docs/development.md) | Lokale kontroller og disponibel testlab |
| [Teststrategi](docs/testing.md) | Kravdekning, testansvar og regler for nye tester |
| [Teststatus](docs/test-results.md) | Observerte resultater og testavgrensninger |

Full avinstallasjon gjøres med `sudo scripts/uninstall.sh`.
Kommandoen stopper miljøene, overfører agentbox-eide prosjektfiler til deg og
fjerner installasjon og tjenestebruker. Se [avinstallasjon](docs/installation.md#avinstallasjon).

Linked worktrees og separat profillagring støttes ikke. Verifiserte
plattformer står i [teststatus](docs/test-results.md), og åpne
verifikasjonshull i [teststrategien](docs/testing.md#åpne-verifikasjonshull).
