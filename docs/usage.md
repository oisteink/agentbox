# Bruk av Agentbox

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
Les `credentials` før start/apply: en kildehenvisning autoriserer lesing av
den navngitte vertsvariabelen og bruk mot de oppgitte destinasjonene.
Bruk ikke en konfigurasjon agenten kan endre til å styre denne tilgangen.

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

Fra 1.0.1 tar `start` bare miljøfilen. Det separate
navneargumentet og `--config` fra 1.0 er fjernet.

```sh
agentbox validate pubnix-codex
agentbox start pubnix-codex
agentbox shell pubnix-codex
```

`start` og `validate` finner kortnavn uten filending under
`~/.config/agentbox/environments/`, eller under
`$XDG_CONFIG_HOME/agentbox/environments/` hvis denne variabelen er satt.
Begge filendingene `.yaml` og `.yml` støttes. Finnes begge for samme kortnavn,
må du velge en eksplisitt fil. Kortnavn leser ikke lokale filer uten filending.

Eksplisitte stier fungerer fortsatt, eksempelvis `agentbox start ./agentbox.yaml`.
Et filnavn med ending, som `agentbox start pubnix-codex.yaml`, bruker en lokal
fil hvis den finnes, ellers samme filnavn i standardkatalogen.

Miljønavnet hentes fra `name` i YAML-filen. Filnavnet velger du selv. `shell` kjører
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
Nøkkelverdien gis ikke som argument eller miljøvariabel. Denne kommandoen gir
likevel Codex den ekte nøkkelen og lagrer innloggingen inne i agenten. Den
bruker ikke proxyens plassholderbeskyttelse. Vanlig ChatGPT device-login
lagrer også Codex sine egne OAuth-data i agenten. Innloggingskoder,
tokens og nøkler skal ikke sjekkes inn eller deles i chat.

Verktøyoppsett, eksempelvis Codex sin `~/.codex/config.toml`, ligger i
containerens `/home/agent`. Eksterne HTTP-baserte MCP-tjenester trenger også
eksplisitt tillatelse for destinasjonen. Agentbox konfigurerer ikke disse
tjenestene eller deres tokens automatisk.

## API-tokens i proxyen

[Se tokenflyten](architecture-c4.md#sekvens-fra-miljøvariabel-til-ekte-api-nøkkel)
fra vertens miljøvariabel til utskifting i proxyen.

Legg en regel i miljøfilen. Den inneholder bare variabelnavnet:

```yaml
network:
  allow:
    - host: mcp.context7.com
      port: 443
credentials:
  - host: mcp.context7.com
    port: 443
    header: Authorization
    env: CONTEXT7_TOKEN=context7_api_key
```

Feltet `env` støtter alias med klientnavnet til venstre og kilden på verten
til høyre:

```yaml
env: hf_token=hugging_face_token
```

Da leses `hugging_face_token` fra terminalen som starter Agentbox. Agenten
får `hf_token` med en generert plassholder. Kildenavnet opprettes ikke som en
ekstra variabel i agenten. `env: hf_token` betyr `hf_token=hf_token`.
Mellomrom rundt navn og likhetstegn ignoreres; navn er versalsensitive.
Samme klientnavn må ha samme kilde i alle regler. Flere klientnavn kan bruke
samme kilde og får egne plassholdere.

Ved **ny opprettelse** gir en manglende eller tom kilde en eksisterende, tom
klientvariabel. Proxyen får ingen nøkkel for referansen. Regelen beholdes,
slik at HTTPS fortsatt inspiseres og ingen tunnel åpnes som reservevei.
Vanlige forespørsler uten plassholder videresendes uten nøkkelinnsetting.

Behold også øvrige nødvendige destinasjoner i `network.allow`. Context7s
[oppsett](https://github.com/upstash/context7#installation) bruker
`https://mcp.context7.com/mcp` og `Authorization: Bearer …`. Sett den rå
nøkkelen (uten `Bearer `) i variabelen på verten, uten shellhistorikk:

```sh
read -rsp 'Context7 API-nøkkel: ' context7_api_key
printf '\n'
export context7_api_key
agentbox start pubnix-codex
```

Eksemplet leser `context7_api_key` på verten og setter `CONTEXT7_TOKEN` i
agenten til en unik plassholder når kilden har verdi. Den ekte
nøkkelen finnes bare i proxyens miljø. Klienten bruker samme variabelnavn:

```sh
# Kjøres inne i agentmiljøet. Variabelen inneholder bare plassholderen.
codex mcp add context7 --url https://mcp.context7.com/mcp \
  --bearer-token-env-var CONTEXT7_TOKEN
```

Eksempelkonfigurasjon: [context7-codex.yaml](../environments/context7-codex.yaml).
Registrer prosjektet og tilpass mounten før start. Gjenta en `credentials`-regel
med samme `env` for å bruke nøkkelen mot flere eksplisitt tillatte destinasjoner.

Proxyen erstatter bare en hel plassholder eller plassholderen etter `Bearer `.
Den beholder prefikset: `Bearer <plassholder>` blir `Bearer <ekte nøkkel>`.
En manglende header eller annen verdi får ingen nøkkel satt inn. Forkortede,
sammensatte eller feilplasserte plassholdere avvises på avlyttet trafikk.
Vanlige tunneler kan ikke inspiseres; plassholderen er ufarlig om den sendes dit.
Dupliserte relevante headere avvises. Tillatte navn er `Authorization`,
`X-API-Key` og `CONTEXT7_API_KEY`. Verdien kan ikke inneholde kontrolltegn.
På avlyttede forespørsler tillates bare GET, HEAD, POST, PUT, PATCH, DELETE
og OPTIONS. TRACE, TRACK, andre metoder og deklarerte request-trailere avvises
før tokeninnsetting. Headeraliaser sammenlignes uten hensyn til bokstavstørrelse
og med `_` lik `-`: én alias erstattes, flere verdier/aliaser avvises.

To praktiske avgrensninger: tekst med `abx-` i andre headerverdier kan gi
403 på inspiserbar trafikk, eksempelvis i en cookie eller request-ID.
Plassholdere i URL/body og ugjennomsiktige tunneler videresendes uten utskifting.
Dette er ufarlige verdier; bare riktig headerregel kan sette inn ekte nøkkel.
Bearer-formen støttes på alle de tillatte auth-headerne; klienten må bruke
formatet tjenesten forventer. En godkjent tjeneste kan reflektere den ekte
nøkkelen i et svar; proxyen skanner ikke svar etter hemmeligheter.

Etter endring av variabel eller regler:

```sh
agentbox proxy apply pubnix-codex
```

Apply kontrollerer først agentprofil, klientnavn, mounts og nettverk. Avslag
her endrer ikke proxyen som kjører; feilmeldingen viser `proxy stop` for
tilbakekalling. Unset alene og gjentatt start av kjørende miljø trekker ikke
tilbake en nøkkel. Bruk `agentbox proxy stop MILJØ` for å stenge tilgangen.

Etter denne kontrollen fjernes gammel proxy og forbindelser før tokenvalidering. Ugyldig verdi
gir stoppet proxy, uten fortsatt tilgang med gammel nøkkel. Kildevariabelen
leses fra den aktuelle vertsterminalen og lagres ikke av CLI-en.
Gjentatt `start` av et uendret, kjørende miljø bytter ikke token; bruk apply.

Proxybytte beholder klientvariabelen og plassholderen. En ikke-tom nøkkel kan
roteres, og en eksisterende klientvariabel kan kobles til en annen kilde,
så lenge begge kilder gir ikke-tom verdi. Tom kan tilsvarende forbli tom.
Et nytt klientnavn krever eksplisitt gjenskaping av agentcontaineren.
Ved tom/ikke-tom overgang stopper apply eller gjenopptak gammel proxy og gir
beskjed om gjenskaping. Agentens eksisterende miljø endres ikke. Dette gjelder
også om kilden mangler når du starter et tidligere opprettet, stoppet miljø.
**`remove` sletter agentens hjem og innlogging; montert prosjekt beholdes.**
Runtime-navn som `HOME`, `PATH`, proxy- og CA-variabler er reservert på
klientsiden av et alias. Kilden på verten kan ha et annet navn.
Velg et rent nøkkelnavn, som `APITOKEN` eller `CONTEXT7_TOKEN`. Listen over
reserverte navn dekker ikke alle verktøy: navn som `SSLKEYLOGFILE`,
`OPENSSL_CONF` og `JAVA_TOOL_OPTIONS` kan endre verktøyoppførsel eller opprette
filer i arbeidsmappen. De skal ikke brukes som tokenreferanser.

Gamle Go-miljøer uten generert plassholder må også gjenskapes eksplisitt.
Ved migrasjon fra tidligere headerinnsetting: fjern `Bearer ` fra den ekte
vertsvariabelen, og la klienten lage dette prefikset. Ingen automatisk migrasjon
av innlogging eller tokenverdier utføres.

```sh
agentbox proxy stop pubnix-codex
unset context7_api_key
```

`proxy stop` fjerner container og Docker-metadata med tokenet, mens agentens
hjem og innlogging beholdes. Gjør dette i hvert miljø som bruker tokenet.
Unset alene endrer ikke kjørende proxyer. Tilbakekalling hos leverandøren
er separat. Fjerner du selve regelen, kan vanlig tunnel igjen tillates av
nettverkspolicyen. Manglende token med beholdt regel gir aldri tunnel-fallback.

Agenten får bare en offentlig CA-katalog med CA og bundle. Curl, Python,
Requests, Node og Codex får CA-innstillinger ved opprettelse. Programmer som
overstyrer dem eller bruker sertifikatpinning må konfigureres særskilt;
sertifikatvalidering skal ikke slås av. Andre images må støtte denne kontrakten.
`agentbox proxy rotate-ca MILJØ` stopper miljøet, erstatter CA og offentlig
bundle og krever en ny start med tokenvariabelen. Hjem/innlogging beholdes.

Miljøvariabler er klartekst i prosessen og lagres i Docker-metadata. Kontroll
over tjenestebrukeren og Docker-instansen kan avsløre dem. Proxyen er betrodd;
en tillatt tjeneste kan også returnere hemmeligheter til agenten i et svar.

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

Endret nettverkspolicy eller tokenregel aktiveres med `proxy apply`.
Agentcontainerens hjem, innlogging og monterte prosjektfiler beholdes.

```sh
agentbox proxy apply pubnix-codex
```

## Hva beholdes?

| Handling | Prosjektfiler på verten | Containerens hjem, innlogging og installerte filer |
| --- | --- | --- |
| Avslutte terminalsesjonen | Beholdes | Beholdes; miljøet kjører videre |
| `stop` og `start` med uendret oppsett | Beholdes | Beholdes |
| Restart av Docker og manuell gjenopptak | Beholdes | Beholdes |
| `remove` og ny `start` | Beholdes | Slettes og opprettes på nytt |
| `proxy apply` eller `proxy stop` | Beholdes | Beholdes |

Hvert miljø har egen innlogging; separat profilvolum finnes ikke i 1.0.
Endret agentimage, mounts, arbeidsprofil eller vertsadresse krever fjerning
og ny opprettelse. Nettverk/tokenregler kan endres med proxy apply. Start av
et stoppet Go-miljø og proxy apply validerer DNS på nytt. Prosjektregistreringer og ACL-er består til du tilbakekaller dem.

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
Etter `start` og `validate` foreslås lagrede kortnavn og lokale filstier.
Filstier fullføres også etter `--key-file`, og kataloger etter `--path`.
Navneoppslag ber ikke om sudo-passord og avbrytes etter to sekunder.

## Vanlige feil

### Codex starter ikke på nytt etter avslutning

Codex 0.166.0 kan forsøke å starte en delt app-server i bakgrunnen ved neste
oppstart. I Agentbox 1.0 er dette observert som `failed to spawn detached
app-server process` med `Operation not permitted`. Feilen betyr ikke at
innloggingen er slettet. Kontroller status og start uten bakgrunnsserver:

```sh
agentbox exec pubnix-codex -- codex login status
agentbox exec pubnix-codex -- codex --no-daemon
```

For en tidligere sesjon kan du bruke
`agentbox exec pubnix-codex -- codex --no-daemon resume`.
Fra 1.0.1 legger utviklingsimaget `--no-daemon` i Codex-launcheren. Eksisterende miljøer beholder sin gamle launcher til den
oppdateres eller miljøet opprettes fra det nye imaget. Ikke bruk `remove`
bare for denne feilen; det sletter hjem og innlogging.

### Andre feil

| Feil | Årsak og neste steg |
| --- | --- |
| `Environment is not running` | Prosjektregistrering starter ikke et miljø. Bruk `start FIL.yaml` før `shell` |
| `Working directory must be inside a mounted project` | Sett `workdir` lik `mounts[].target` eller en eksisterende undermappe |
| `No two collision-free /28 subnets` | Velg et ledig adresseområde etter [installasjonsveiledningen](installation.md#velg-adresseområde) |
| `Host addresses changed` | Adressevakten har stoppet miljøet; fjerning og ny opprettelse kreves |
| Verktøy trenger Unix-sockets | Profilen blokkerer nye Unix-sockets. Velg kompatible verktøy; ikke svekk isoleringen automatisk |
