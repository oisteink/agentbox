# Bruk av Agentbox

Kjør kommandoene som utvikleren på verten. Agentbox velger sin egen rootless
Docker-instans; du trenger ikke bytte Docker-context eller sette `DOCKER_HOST`.
Se [installasjon](installation.md) hvis `doctor` ikke fungerer.

## Utskrift og automatisering

Standardutskriften har tabeller for lister, navngitte felt for detaljer og
feilmeldinger på stderr. `abx validate MILJØFIL` skriver `OK` eller en konkret
feil. En kommando som kjøres i miljøet, gir sin exitkode tilbake til skallet.

Bruk `--json` for maskinlesbar utskrift. Flagget kan stå før kommandoen eller
på kommandonivå; for `exec` må det stå før miljønavnet. Alt etter miljønavnet
er kommandoargumenter. `--` skiller eksplisitt mellom abx og kommandoen.

```sh
abx --json status
abx image ls --json
printf 'input' | abx --json exec example-codex -- cat
```

Utdata er JSON Lines. Siste linje er nøyaktig ett resultat:

```json
{"type":"result","ok":true,"data":{}}
{"type":"result","ok":false,"error":{"code":"invalid_configuration","message":"persistent must be a boolean"}}
```

Prosesskjøring, editor og logger kan først sende hendelser med
`{"type":"output","stream":"stdout","data":"tekst"}`; `stream` kan også være
`stderr`. Prosessresultatet har `exit_code`, og en feilende kommando har
`ok: false` og `error.code: command_failed`. Ctrl-C gir `interrupted` og
`exit_code: 130` når abx rekker å håndtere signalet. JSON-modus bruker ingen TTY,
videresender stdin og skriver alle hendelser og resultater på stdout.

Håndterte feil gir exitkode 0 i JSON-modus. Les alltid `ok`, `error.code` og
`exit_code` i sluttresultatet. Manglende sluttresultat betyr avbrutt eller
ufullstendig kjøring. Ukjente argumenter gir `invalid_arguments`; feil i
kontrolltransporten gir `control_protocol_error`; øvrige operasjonsfeil gir
`operation_failed` eller `control_failed`. Feil kan ha et ekstra `details`-felt.
`--json --help` returnerer hjelpeteksten i `data.help`.

`--yes` gir samtykke der en handling krever bekreftelse. JSON spør aldri;
uten samtykke gir slike handlinger `confirmation_required` med berørte
ressurser i `error.details.affected`. Samtykke endrer ikke hvordan handlingen utføres.

Kommandoens egne utdata kan inneholde hemmeligheter. JSON-innramming renser
ikke disse. Ugyldige UTF-8-bytes erstattes med erstatningstegn ved visning;
den private agentloggen beholder bytes fra kommandoen.

## Prosjekt og miljø

| Begrep | Eksempel | Betydning |
| --- | --- | --- |
| Prosjekt | `example` | Registrert vertsmappe, eksempelvis `~/src/example` |
| Miljø | `example-codex` | Agentcontainer, proxy og nettverk med egen livssyklus |
| Miljøfil | `~/.config/agentbox/environments/example-codex.yaml` | Valgt image, prosjektmonteringer og nettverkspolicy |
| Imageoppskrift | `~/.config/agentbox/images/codex/` | Redigerbar Dockerfile og byggkontekst |

Ett miljø kan montere flere registrerte prosjekter. Samme prosjekt kan brukes
i flere miljøer, men alle med skrivetilgang arbeider på de samme filene.
Miljønavnet og prosjektets navn trenger ikke være like.

## Registrer en prosjektmappe

```sh
abx project add example --path "$HOME/src/example"
abx project list
abx project check example
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
Les `credentials` før `start`, `run` og `proxy apply`: en kildehenvisning
autoriserer lesing av den navngitte vertsvariabelen og bruk mot de oppgitte
destinasjonene.
Bruk ikke en konfigurasjon agenten kan endre til å styre denne tilgangen.

```yaml
name: example-codex
image: codex
workdir: /home/agent/src/example
command: ["codex"]
mounts:
  - project: example
    target: /home/agent/src/example
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

`start` leser miljønavnet fra miljøfilen.

```sh
abx validate example-codex
abx start example-codex
abx shell example-codex
```

`start`, `run`, `validate` og `proxy apply` finner kortnavn uten filending under
`~/.config/agentbox/environments/`, eller under
`$XDG_CONFIG_HOME/agentbox/environments/` hvis denne variabelen er satt.
Begge filendingene `.yaml` og `.yml` støttes. Finnes begge for samme kortnavn,
må du velge en eksplisitt fil. Kortnavn leser ikke lokale filer uten filending.

Eksplisitte stier fungerer, eksempelvis `abx start ./agentbox.yaml`.
Et filnavn med ending, som `abx start example-codex.yaml`, bruker en lokal
fil hvis den finnes, ellers samme filnavn i standardkatalogen.

Miljønavnet hentes fra `name` i YAML-filen. Filnavnet velger du selv. `start`
klargjør miljøet med en oppholdsprosess. `shell` kjører `command` fra miljøets
lagrede konfigurasjon, som kan være Codex eller Bash. Du kan åpne Bash
separat uten å endre konfigurasjonen:

```sh
abx exec example-codex -- bash
```

Med standardinnstillingen `persistent: true` lukker du terminalsesjonen ved å
avslutte programmet eller skallet. Miljøet fortsetter å kjøre. Åpne det igjen med `abx shell example-codex`.

```sh
abx status
abx stop example-codex
```

Et stoppet miljø gjenopptas med samme `start`-kommando og miljøfil.
Miljøene startes ikke automatisk etter vertsreboot.

## Miljø uten bevart containerlag

Sett dette på toppnivå i miljøfilen:

```yaml
persistent: false
```

Standardverdien er `true`. Med `false` klargjør `start` miljøet i bakgrunnen
og varsler om at det er midlertidig. `shell` varsler før den kjører miljøets
kommando og fjerner miljøet når kommandoen avsluttes, også ved feil og Ctrl-C:

```sh
abx start example-codex
abx shell example-codex
```

Etter fjerning oppretter neste `start` en ny container fra imaget. Hjem, innlogging,
installerte filer og logger fra økten slettes; prosjektfilene beholdes.
`stop` fjerner også et slikt miljø, selv om du ikke har kjørt `shell`.

Bare én `shell` kan kjøre i miljøet om gangen. `exec` kan brukes til ekstra
kommandoer i det klargjorte miljøet; det utløser ikke opprydding. Når `shell`
avsluttes, fjernes hele miljøet, inkludert eventuelle ekstra prosesser.
`run` fjerner alltid miljøet, uansett verdien av `persistent`.

Ved SIGKILL eller vertskrasj kan ressurser gjenstå. En allerede reservert
shell-økt gjenbrukes ikke; fjern miljøet med `abx remove NAVN` og start på nytt.
Endring av `persistent` for et eksisterende miljø krever også `remove` og ny
`start`. Da slettes containerlaget; monterte prosjektfiler består.

## Midlertidig kjøring

`abx run FIL.yaml` kjører miljøfilens `command` én gang i terminalen og
fjerner deretter agent, proxy, nettverk og containerlag. Monterte prosjektfiler
beholdes. Lagre dette som `task.yaml`; det bruker lokalt `codex`-image og
registrert prosjekt `example`:

```yaml
name: example-task
image: codex
command: ["bash"]
mounts:
  - project: example
    target: /workspace
```

```sh
abx run ./task.yaml
```

`run` støtter samme kortnavn og miljøfiler som `start`. Kommandoen kjøres i
forgrunnen med automatisk opprydding.

Bruk et ledig miljønavn. Et eksisterende miljø med samme navn avvises uten
endringer. Kommandoens exitkode returneres etter opprydding. Ctrl-C avbryter
kjøringen og venter på oppryddingen; oppryddingsfeil gir feilstatus.
Containerlaget, innloggingen og miljøets logger slettes. Legg filer som
skal beholdes i prosjektmountene. Ved SIGKILL eller vertskrasj kan ressurser
gjenstå; kontroller `abx status` og fjern miljøet med `abx remove NAVN`.

Når både stdin og stdout er terminaler, brukes en interaktiv terminal. Ellers
videresendes stdin uten terminal, og kommandoens stdout og stderr holdes atskilt.
Utdata lagres også i en privat, størrelsesbegrenset logg hos tjenestebrukeren.

## Innlogging og verktøyoppsett

Logg inn i Codex inne i miljøet. For headless ChatGPT-innlogging beskriver
[OpenAI Docs](https://learn.chatgpt.com/docs/auth) `codex login --device-auth`:

```sh
abx exec example-codex -- codex login --device-auth
```

Tillat innloggingsmetodens nødvendige destinasjoner først. Bruk
`cli_auth_credentials_store = "file"` i Codex-konfigurasjonen for eksplisitt
fillagring. Vertens keyring, personlige Codex-oppsett, miljøvariabler og
SSH-agent deles ikke automatisk inn.

API-nøkkel kan gis fra en privat fil på verten:

```sh
chmod 600 /sti/til/privat-nokkelfil
abx login-api-key example-codex --key-file /sti/til/privat-nokkelfil
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
abx start example-codex
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
abx proxy apply example-codex
```

Apply kontrollerer først agentprofil, klientnavn, mounts og nettverk. Avslag
her endrer ikke proxyen som kjører; feilmeldingen viser `proxy stop` for
tilbakekalling. Unset alene og gjentatt start av kjørende miljø trekker ikke
tilbake en nøkkel. Bruk `abx proxy stop MILJØ` for å stenge tilgangen.

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

```sh
abx proxy stop example-codex
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
`abx proxy rotate-ca MILJØ` stopper miljøet, erstatter CA og offentlig
bundle og krever en ny start med tokenvariabelen. Hjem/innlogging beholdes.

Miljøvariabler er klartekst i prosessen og lagres i Docker-metadata. Kontroll
over tjenestebrukeren og Docker-instansen kan avsløre dem. Proxyen er betrodd;
en tillatt tjeneste kan også returnere hemmeligheter til agenten i et svar.

## Logger og endret nettverkspolicy

Fra en annen terminal på verten:

```sh
abx logs example-codex
abx logs example-codex --proxy
```

Proxyloggen viser destinasjon og resultat uten URL-sti eller query.
Agentutdata lagres i private, størrelsesbegrensede logger uten generell
innholdsfiltrering; utdata kan inneholde hemmeligheter.
`logs` viser et utsnitt, og følger ikke nye hendelser kontinuerlig.

Legg nødvendige eksakte navn og porter til under `network.allow`. Bare HTTP
på 80 og HTTPS via CONNECT på 443 støttes. Underdomener tillates ikke
automatisk. Imagebygging og henting av baseimages skjer på kontrollsiden og bruker
ikke denne listen.

Endret nettverkspolicy eller tokenregel aktiveres med `proxy apply`.
Agentcontainerens hjem, innlogging og monterte prosjektfiler beholdes.

```sh
abx proxy apply example-codex
```

## Hva beholdes?

| Handling | Prosjektfiler på verten | Containerens hjem, innlogging og installerte filer |
| --- | --- | --- |
| Avslutte `shell` med `persistent: true` | Beholdes | Beholdes; miljøet kjører videre |
| Avslutte `exec` | Beholdes | Beholdes til miljøet fjernes |
| Avslutte `shell` med `persistent: false` | Beholdes | Slettes sammen med miljøet og dets logger |
| Avslutte `run`, også med Ctrl-C | Beholdes | Slettes sammen med miljøet og dets logger |
| `stop` og `start` med `persistent: true` og uendret oppsett | Beholdes | Beholdes |
| `stop` med `persistent: false` | Beholdes | Slettes |
| Restart av Docker og manuell gjenopptak av vedvarende miljø | Beholdes | Beholdes |
| `remove` og ny `start` | Beholdes | Slettes og opprettes på nytt |
| `proxy apply` eller `proxy stop` | Beholdes | Beholdes |

Vedvarende miljøer beholder egen innlogging; separat profilvolum støttes ikke.
Endret agentimage, mounts, arbeidsprofil eller vertsadresse krever fjerning
og ny opprettelse. Nettverk/tokenregler kan endres med proxy apply. Start av
et stoppet miljø og proxy apply validerer DNS på nytt. Prosjektregistreringer
og ACL-er består til du tilbakekaller dem.

## Bytt prosjekt eller image

Registrer neste prosjekt, lag en egen miljøfil og start miljøet med et nytt
navn. Det eksisterende miljøet kan fortsette å kjøre. For et annet verktøy
mot samme prosjekt bruker du også et nytt miljønavn og velger image i YAML.

Alle agentimages bygges fra lokale oppskrifter. Opprett for eksempel et
JavaScript-miljø:

```sh
abx image new js
abx image edit js
abx image build js
abx image ls
abx image inspect js
```

`new` lager Dockerfile og `.dockerignore` uten å overskrive eksisterende
kataloger. Standardmalen har Bash, CA-sertifikater, curl, Git, Python og
nettverksverktøy. Bytt eller utvid Dockerfilen med verktøyene du trenger;
`FROM node:22-bookworm-slim` kan for eksempel brukes som utgangspunkt.
Codex-malen velges med `abx image new codex --template codex` og inkluderer
Codex CLI 0.166.0 og launcheren med `--no-daemon`.

Eksempelmaler og miljøfiler:

| Verktøy | Mal | Kommando | Miljøfil |
| --- | --- | --- | --- |
| Codex 0.166.0 | `codex` | `codex` | [codex.yaml](../environments/codex.yaml) |
| OpenCode 1.19.5 | `opencode` | `opencode` | [opencode.yaml](../environments/opencode.yaml) |
| Claude Code 2.1.316 | `claude-code` | `claude` | [claude-code.yaml](../environments/claude-code.yaml) |

Opprett og bygg ønsket image, for eksempel:

```sh
abx image new opencode --template opencode
abx image build opencode
```

Kopier miljøfilen til `~/.config/agentbox/environments/` og endre
`mounts[].project` til et registrert prosjekt. Eksemplene bruker API-nøkler:
Codex trenger `OPENAI_API_KEY` i vertens miljø; OpenCode og Claude Code
trenger `ANTHROPIC_API_KEY`. Eksporter nøkkelen før `abx start` eller `abx run`,
slik at proxyen kan erstatte agentens plassholder. OpenCode-eksemplet bruker
Anthropic; velg en Anthropic-modell med `/models` i verktøyet.

Eksemplene tillater bare leverandørens API på port 443. Abonnementsinnlogging,
andre modelltilbydere, MCP, pakkeregistre og verktøyenes tilleggstjenester
krever egne tillatte domener. [OpenCode](https://opencode.ai/docs/) og
[Claude Code](https://code.claude.com/docs/en/setup) installeres via deres
npm-pakker med versjonen angitt i Dockerfilen. Endre versjonen med
`abx image edit NAVN` før ny bygging. OpenCode-malen setter `NO_PROXY` for
loopback fordi terminalgrensesnittet bruker en lokal HTTP-server; dette
åpner ingen ekstern nettverkstilgang. Claude Code-malen slår av automatisk
oppdateringssjekk med `DISABLE_AUTOUPDATER=1`.

Malene og miljøfilene er utgangspunkt. Tilpass pakker, versjoner, kommando og
nettverkspolicy til egen bruk. Prøveomfanget står i [teststatus](test-results.md).

`edit NAVN` åpner Dockerfilen i `$VISUAL`, deretter `$EDITOR`, eller `editor`
hvis ingen er satt. Editorargumenter støttes, for eksempel `VISUAL="code --wait"`.
Editoren kjører som deg med oppskriftskatalogen som arbeidskatalog, og arver
terminalen. Du kan også åpne `.dockerignore` og hjelpeskript derfra. Kommandoen
returnerer editorens exitkode. Redigering er tillatt mens imaget brukes;
bygging skjer først når du kjører `image build`.

Oppskriftene ligger under `~/.config/agentbox/images/`, eller
`$XDG_CONFIG_HOME/agentbox/images/`. Hele katalogen er byggkontekst, slik at
vanlig `COPY` og hjelpeskript fungerer. Symbolske lenker pakkes som lenker;
lenker ut av konteksten og spesialfiler avvises. Hele konteksten overføres
til en privat midlertidig katalog på kontrollsiden, mens Docker behandler
`.dockerignore` under byggingen. Hold oppskrifter og kontekst utenfor agentens
skrivbare mounts. Byggingen bruker kontrollsidens nettverkstilgang.

Velg `image: js` i miljøfilen. `ls` viser oppskrifter med status `unbuilt`
eller `built`, tag, ID og containere. `inspect` viser også oppskriftsstien.
Status forteller om et bygget image finnes; den sporer ikke endringer i
Dockerfilen. Bygging skjer eksplisitt, uten automatisk pull ved miljøstart.
Baseimages i `FROM` kan hentes fra registry som ved vanlig Docker-bygging.

Bygg og `abx image rm js` avvises så lenge en eksisterende container bruker
samme image-ID, også når containeren er stoppet. Fjern de berørte miljøene
med `abx remove MILJØ` før ombygging. `remove` sletter containerlaget,
inkludert hjem og innlogging; behold nødvendige arbeidsfiler i prosjektmounts.
`image rm` fjerner det bygde imagets tag og beholder oppskriften for senere bygg.

Images må være amd64 eller arm64, støtte UID 0 og ha `/bin/sh` og
`sleep infinity`, samt støtte [CA-oppsettet](#api-tokens-i-proxyen).
Deklarerte `VOLUME`-mounts avvises. Alle images bruker samme nettverks- og
syscallbegrensninger; se [arkitekturvalg](decisions.md#lokale-imageoppskrifter).

Proxyimaget er en intern komponent som installeren bygger når det mangler.
`abx proxy build` bygger det på nytt fra installert kilde. Det vises ikke i
`image ls` og har ingen brukeroppskrift. Alle containere med samme proxyimage-ID
må fjernes før bygging; stopp alene frigjør ikke imaget. For hvert berørt miljø:

```sh
abx stop example-codex
abx proxy stop example-codex
# Når alle berørte proxycontainere er fjernet:
abx proxy build
abx start example-codex
```

`proxy stop` fjerner proxycontaineren og dens tokenmetadata, mens agentens
containerlag beholdes. Neste `start` eller `proxy apply` oppretter proxyen på
nytt. Eksporter nødvendige tokenvariabler før gjenopptak. Oppdatering av
kontrollkoden gjøres med installeren etter at miljøene er stoppet.

## Reparer eller tilbakekall prosjekttilgang

Stopp alle miljøer som bruker prosjektet først, også de med read-only-mounts.
Velg deretter operasjonen du trenger:

```sh
abx project check example
abx project repair example
# Alternativt, for å avslutte delingen:
abx project revoke example
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
source <(abx completion bash)
```

Installeren legger inn completion for nye skall med `bash-completion` aktivert.
Tab foreslår kommandoer, flagg, eksisterende miljønavn, registrerte prosjekter
og lokale imageoppskrifter etter `image edit`, `build`, `inspect` og `rm`.
Etter `start`, `run`, `validate` og `proxy apply` foreslås lagrede kortnavn og
lokale filstier.
Filstier fullføres også etter `--key-file`, og kataloger etter `--path`.
Navneoppslag ber ikke om sudo-passord og avbrytes etter to sekunder.

## Vanlige feil

### Codex starter ikke på nytt etter avslutning

Codex-malen bruker `--no-daemon` fordi isoleringsprofilen blokkerer
oppstart av delt app-server. Hvis et eget image gir
`failed to spawn detached app-server process` med `Operation not permitted`,
kontroller innloggingen og kjør uten bakgrunnsserver:

```sh
abx exec example-codex -- codex login status
abx exec example-codex -- codex --no-daemon
```

Gjenoppta en sesjon med `codex --no-daemon resume`. Feilen krever ikke
fjerning av miljøet; `remove` sletter hjem og innlogging.

### Andre feil

| Feil | Årsak og neste steg |
| --- | --- |
| `Environment is not running` | Prosjektregistrering starter ikke et miljø. Bruk `start FIL.yaml` før `shell` |
| `Working directory must be inside a mounted project` | Sett `workdir` lik `mounts[].target` eller en eksisterende undermappe |
| `No two collision-free /28 subnets` | Velg et ledig adresseområde etter [installasjonsveiledningen](installation.md#velg-adresseområde) |
| `Host addresses changed` | Adressevakten har stoppet miljøet; fjerning og ny opprettelse kreves |
| Verktøy trenger Unix-sockets | Profilen blokkerer nye Unix-sockets. Velg kompatible verktøy; ikke svekk isoleringen automatisk |
