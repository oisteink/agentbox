# Bruk av Agentbox

Kjør kommandoene som utvikleren på verten. Agentbox velger sin egen rootless
Docker-instans; du trenger ikke bytte Docker-context eller sette `DOCKER_HOST`.
Se [installasjon](installation.md) hvis `doctor` ikke fungerer.

## Utskrift og automatisering

Standardutskriften har tabeller for lister, navngitte felt for detaljer og
feilmeldinger på stderr. `abx validate MILJØFIL` skriver `OK` eller en konkret
feil. En kommando som kjøres i miljøet, gir sin exitkode tilbake til skallet.

Bruk `--json` for maskinlesbar utskrift. Flagget kan stå før kommandoen eller
på kommandonivå. For exec står abx-flagg før `--`; alt etter `--` er
kommandoargumenter, også flagg som heter `--json` eller `--keep-running`.

```sh
abx --json status
abx image list --json
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

## Mount og miljø

| Begrep | Eksempel | Betydning |
| --- | --- | --- |
| Mount | `example` eller `profile` | Registrert katalog eller navngitt Docker-volum |
| Miljø | `example-codex` | Agentcontainer, proxy og nettverk med egen livssyklus |
| Miljøfil | `~/.config/agentbox/environments/example-codex.yaml` | Valgt image, mounts og nettverkspolicy |
| Imageoppskrift | `~/.config/agentbox/images/codex/` | Redigerbar Dockerfile og byggkontekst |

Ett miljø kan montere flere registrerte mounts. Samme mount kan brukes
i flere miljøer, men alle med skrivetilgang arbeider på de samme filene.
Miljønavnet og kildens navn trenger ikke være like.

## Registrer delingskilder

```sh
abx mount add example "$HOME/src/example"
abx mount add profile --volume
abx mount list
abx mount check example
abx mount check example --fix
```

En registrert kilde har et navn og typen `directory` eller `volume`. Begge
brukes med `source` i miljøfilen. En vertsmappe må finnes og eies av deg.
Et volum opprettes av Docker i Agentbox-instansen og har ingen brukerdefinert
vertssti. List viser type, sti der relevant og registreringsstatus.

Katalogregistrering gir tjenestebrukeren tilgang gjennom ACL-er. Begge brukerne
får tilgang til innholdet og standard-ACL for nye filer. Foreldrekataloger får
traversering uten listetilgang. Overlappende røtter, hardlenkede ordinære filer,
spesialfiler og ukjente eiere avvises. Symlinker følges ikke ved ACL-endring,
og nestede mountpunkter utelates. Andre brukeres effektive rettigheter bevares.

Samme navn og kilde kan registreres igjen, også etter tilbakekalling.
Annen type, sti eller katalogidentitet ved samme navn gir konflikt.
`check` viser OK eller konkrete identitets-/tilgangsfeil. `--fix` reparerer
katalog-ACL-er med samme operasjoner som registrering og tilbakekalling;
katalogtildeling krever at brukerne er stoppet. Tilbakekalte kilder gjenåpnes
ikke av fix. Volumkontroll sjekker driver og eiermerking, og gjenskaper aldri
et manglende volum. Uferdig tildeling vises som `adding`; rett årsaken og prøv
`add` igjen (eller `check --fix` for kataloger). Ved ufullstendig fjerning må
`mount remove` prøves igjen.

### Bevar profiler og hjem

```yaml
mounts:
  - source: example
    target: /workspace
  - source: profile
    target: /home/agent/.config/tool
```

`mode: ro` eller `rw` velges per miljø. Samme volum kan brukes av flere miljøer.
Navngitte volumer overlever `stop`, `remove`, `run` og imagebytte. Innhold fra
imaget kopieres ikke automatisk inn i et tomt volum (`volume-nocopy`).

Agentens `HOME` er `/home/agent`. Du kan montere en katalog eller et volum der,
eller på en verktøyspesifikk understi. Montering på `/root` endrer ikke HOME;
bruk den profilstien verktøyet faktisk bruker. `~` utvides av det aktuelle
skallet, og er ingen egen mount-syntaks. Operatørens hjem deles ikke automatisk.
Montering av hele HOME skjuler imagets opprinnelige hjemmekatalog.

### Tilbakekall eller fjern en kilde

```sh
abx mount revoke example
abx mount remove example
abx mount remove profile --yes
```

`revoke` beholder registrering og data, og nekter nye monteringer. For en
katalog legges også en eksplisitt deny-ACL på roten. For et volum er sperren
registreringsbasert. Kjører miljøer med kilden, vises navnene og en advarsel:
eksisterende monteringer og åpne filhåndtak kan beholde tilgang. Ingen miljøer
stoppes automatisk. `add` med samme kilde åpner registreringen igjen.

`mount remove` avregistrerer etter fullført rydding. Kjørende katalogbrukere
må stoppes; kommandoen ber om samtykke og viser hvilke miljøer som berøres.
For ikke-persistente miljøer slettes også containerlaget. Volumbrukere må
fjernes helt, også stoppede containere, før Docker lar volumet slettes.
Derfor viser samtykket både miljønavn og om de stoppes eller fjernes.
`--yes` gir samtykke; JSON uten samtykke gir `confirmation_required` før endring.

For kataloger beholdes filer og eierskap. Service-ACL-er og ubrukte
traverseringsgrants ryddes; operatør-ACL beholdes på agentbox-eide filer.
Tjenestebrukerens eiertilgang kan derfor bestå. Avregistrerte filer inngår
heller ikke i en senere avinstallasjons eierskapsrydding. Resultatet oppgir
rettighets- og eierskapsgrensen. Vanlig kontrollhjelper har ikke root/chown.
For volumer slettes både Docker-volumet og alt innholdet.

Avslag beholder registreringen. Feil under rydding beholder registreringen
som `removing`, med identitet og grunnlag for nytt forsøk. Add, revoke og fix
åpner ikke en slik registrering. Miljøfiler slettes ikke; de kan brukes igjen
når kilden er registrert og aktiv. Fremmede Docker-containerreferanser sperrer
fjerning fremfor å bli stoppet eller slettet.

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
  - source: example
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

`mounts[].source` viser til mount-registeret. `target` er stien inne i
containeren; `workdir` må ligge i et valgt mount. Katalogmounts krever en eksisterende undermappe.
Velg `mode: ro` for skrivebeskyttet montering. Legg til flere oppføringer for
flere mounts, med ulike mål som ikke overlapper.

Eksempelet tillater bare `api.openai.com:443`. Det er ingen komplett liste
for alle innloggingsmetoder eller Codex-funksjoner. Velg nødvendige
agentdestinasjoner eksplisitt. `network: {allow: []}` stenger ekstern tilgang.
Bruk `command: ["bash"]` for å åpne et vanlig skall mens du prøver filtilgang.

## Start, åpne og avslutt

`start` leser miljønavnet fra miljøfilen.

```sh
abx validate example-codex
abx start example-codex
```

`start`, `run`, `exec`, `validate` og `proxy apply` finner kortnavn uten filending under
`~/.config/agentbox/environments/`, eller under
`$XDG_CONFIG_HOME/agentbox/environments/` hvis denne variabelen er satt.
Begge filendingene `.yaml` og `.yml` støttes. Finnes begge for samme kortnavn,
må du velge en eksplisitt fil. Kortnavn leser ikke lokale filer uten filending.

Eksplisitte stier fungerer, eksempelvis `abx start ./agentbox.yaml`.
Et filnavn med ending, som `abx start example-codex.yaml`, bruker en lokal
fil hvis den finnes, ellers samme filnavn i standardkatalogen.

Miljønavnet hentes fra `name` i YAML-filen. `start` klargjør miljøet og kjører
filens `command` i terminalen. `exec` kjører en eksplisitt kommando, med samme
klargjøring og opprydding:

```sh
abx start example-codex
abx exec example-codex -- bash
abx exec example-codex -- echo Bananmaskinoperator
```

Avslutt programmet eller skallet for å avslutte kjøringen. Når siste aktive
kjøring er ferdig, stopper abx miljøet det selv startet. Flere terminaler kan
bruke samme miljø samtidig. Den første som avslutter, stopper ikke de andre.
Med standardverdien `persistent: true` beholdes containerlaget, hjem og
innlogging ved stopp. Neste start gjenopptar laget når oppsettet er uendret.

Bruk `--keep-running` for å beholde miljøet kjørende etter kommandoen:

```sh
abx start example-codex --keep-running
abx exec example-codex --keep-running -- echo klar
abx stop example-codex
```

Flagget gjelder hele den aktuelle kjøreperioden. Enhver start/exec kan sette
det; gjentatt bruk gir ingen teller. Kjøringer uten flagget nullstiller det
ikke. `stop` stopper miljøet selv om kjøringer er aktive eller flagget er satt.
Et miljø som allerede kjører uten automatisk eierskap, beholdes også.
`status` viser antall aktive kjøringer og om miljøet skal beholdes kjørende.

Endret image, konfigurasjon eller vertsadresse kan erstatte containerlaget
ved neste oppstart av stoppet miljø; eksplisitte mounts beholdes. Kjørende
miljø beholder oppsettet og gir beskjed om ventende endringer. Start bruker
da den lagrede kommandoen; exec bruker argumentene du oppgir etter `--`.
Start/exec gjenåpner ikke en proxy du har stoppet mens agenten kjører.
`proxy apply` aktiverer eksplisitte nettverks-/tokenendringer.
Miljøer starter ikke automatisk etter vertsreboot.

## Miljø uten bevart containerlag

Sett `persistent: false` på toppnivå i miljøfilen. Ved stopp fjernes
containere, nettverk, containerlag og logger. Registrerte mounts og volumdata
beholdes. Start varsler om at miljøet er ikke-persistent.

```sh
abx start example-codex
```

Neste start gir en ny container. Med `--keep-running` kan du bruke samme
ikke-persistente container til flere kommandoer og økter frem til eksplisitt
`abx stop example-codex`. Flere aktive kjøringer deler den til siste avslutning.

## Midlertidig kjøring

`abx run CONFIG` kjører filens kommando i en separat midlertidig instans og
fjerner instansen etter bruk, uansett filens `persistent`. Et vanlig miljø
fra samme fil og andre run-instans­er fortsetter uavhengig.

```sh
abx run example-codex
```

Instansen får et navn som `example-codex-run-a1b2c3d4e5f6`. Navnet vises ved
oppstart, i status og i JSON-sluttresultatet. Det kan brukes med logs, stop
og remove mens instansen finnes. Lange miljønavn avkortes slik at hele
instansnavnet holder seg innen 48 tegn. Etter opprydding forsvinner raden.
Miljøfilen, mount-registreringer og mountdata beholdes.

Når stdin og stdout er terminaler, brukes en interaktiv terminal. Ellers
videresendes stdin, med atskilt stdout/stderr. Dette gjelder start, exec og run.
Kommandoens exitkode returneres etter opprydding; JSON bruker `exit_code` i
resultatet. Ctrl-C avslutter kjøringen og venter på opprydding.

## Avbrutte kjøringer

Den eksisterende vakten oppdager døde klienter og kontrollhjelpere gjennom
Linux-prosessidentitet. Den rydder siste automatiske kjøring, men respekterer
`--keep-running` og andre aktive kjøringer. Så lenge miljøet blir stående,
kan containerprosesser fortsette etter klientavbrudd eller krasj. `stop`
avslutter dem.

Hvis Docker-oppstarten av en kommando ikke kan bekreftes, stoppes miljøet.
`launch_unknown` betyr at samme container-ID ikke kan startes igjen før
Docker bekrefter utfallet. Abx forsøker avklaringen i neste handling. Ved
fortsatt ukjent utfall kan eksplisitt remove fjerne containeren; det sletter
containerlaget. Et persistent lag slettes ikke automatisk for å skjule feilen.
Mountdata beholdes. Tilgang til operatørens prosessmetadata under `/proc`
kreves; manglende observasjon rapporteres og regnes ikke som en død sesjon.

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

Til et kjørende miljø kan API-nøkkel gis fra en privat fil på verten:

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
Registrer mountet og tilpass mounten før start. Gjenta en `credentials`-regel
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
Nye klientnavn og tom/ikke-tom overgang krever ny agentcontainer. Start av
stoppet miljø erstatter containeren automatisk; eksplisitte mounts består.
Proxy apply fjerner gammel proxy og avviser slik overgang på samme agent.
Kjørende start/exec beholder oppsettet med pending-beskjed, uten å gjenåpne
en stoppet proxy. Bruk proxy stop for lokal tilbakekalling.
Kontrolloperasjoner deler lås; et pågående imagebygg kan forsinke stoppet.
**`remove` sletter containerlaget; data i eksplisitte mounts beholdes.**
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
Agentcontainerens hjem, innlogging og monterte filer i katalogmounts beholdes.

```sh
abx proxy apply example-codex
```

## Hva beholdes?

| Handling | Filer i katalogmounts på verten | Containerens hjem, innlogging og installerte filer |
| --- | --- | --- |
| Siste start/exec avsluttes, persistent true | Beholdes | Beholdes; miljøet stopper uten keep-running |
| Siste start/exec avsluttes, persistent false | Beholdes | Slettes uten keep-running |
| Start/exec med keep-running | Beholdes | Beholdes frem til eksplisitt stop/remove |
| Avslutte `run`, også med Ctrl-C | Beholdes | Slettes sammen med miljøet og dets logger |
| `stop` og `start` med `persistent: true` og uendret oppsett | Beholdes | Beholdes |
| `stop` med `persistent: false` | Beholdes | Slettes |
| Restart av Docker og manuell gjenopptak av vedvarende miljø | Beholdes | Beholdes |
| `remove` og ny `start` | Beholdes | Slettes og opprettes på nytt |
| `proxy apply` eller `proxy stop` | Beholdes | Beholdes |

Vedvarende miljøer beholder innlogging i containerlaget. Bruk eksplisitt mount
på profilstien for å bevare den ved containerfjerning.
Endret agentimage, mounts, arbeidsprofil eller vertsadresse krever fjerning
og ny opprettelse. Nettverk/tokenregler kan endres med proxy apply. Start av
et stoppet miljø og proxy apply validerer DNS på nytt. Mount-registreringer
og ACL-er består til du tilbakekaller dem.

## Bytt mount eller image

Registrer neste mount, lag en egen miljøfil og start miljøet med et nytt
navn. Det eksisterende miljøet kan fortsette å kjøre. For et annet verktøy
mot samme mount bruker du også et nytt miljønavn og velger image i YAML.

Alle agentimages bygges fra lokale oppskrifter. Opprett for eksempel et
JavaScript-miljø:

```sh
abx image new js
abx image edit js
abx image build js
abx image list
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
`mounts[].source` til et registrert mount. Eksemplene bruker API-nøkler:
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

## Lokale maler, redigering og bygg

```sh
abx image new js
abx image new default --template base
abx image new task --template default
abx image edit js
abx image list
abx image inspect js
abx image build js
abx image remove js
```

Uten `--template` brukes din lokale `default`, ellers medfølgende `base`.
Du kan velge alle lokale oppskrifter som mal, også ubygde. Medfølgende
base/codex/opencode/claude-code brukes når ingen lokal oppskrift har samme
navn. Medfølgende filer ligger i pakkens templates-katalog, på verten under
`/opt/agentbox/lib/agentbox/templates/`. Reinstallasjon gjenoppretter dem;
dine filer under XDG/~/.config/agentbox/images beholdes.

New kopierer hele malens byggkontekst til en selvstendig katalog, inkludert
`.dockerignore`, hjelpeskript, underkataloger og lenker som lenker. Den
overskriver ikke eksisterende mål. Senere endringer i malen endrer ikke kopien.

Edit åpner Dockerfilen i `$VISUAL`, deretter `$EDITOR`, ellers `editor`.
Siterte argumenter støttes, eksempelvis `VISUAL="code --wait"`. Editoren
arver vanlig terminal og miljø, med oppskriften som arbeidskatalog. Du kan
redigere `.dockerignore` og hjelpeskript derfra. Etterpå vises om konteksten
ble endret, også om editoren avsluttet med feil. JSON-resultatet har `changed`
og `exit_code`. Edit starter ingen bygging.

List viser `unbuilt`, `stale` eller `built`; inspect viser også ID, inputdigest
og brukere. Sti, filbytes, modus og lenkemål inngår i endringskontrollen.
Bare endret mtime/eier utløser ikke bygg. Hele overførte konteksten teller,
også filer ekskludert av `.dockerignore`; slike endringer kan derfor gi ekstra
bygg. Docker behandler selv ignore-reglene og vanlig COPY under byggingen.
Lenker følges ikke ved overføring; utrygge lenker og spesialfiler avvises.
Hold konteksten utenfor agentens skrivbare mounts. Hele konteksten går til en
privat midlertidig katalog på kontrollsiden før Docker filtrerer den.

Start, run og exec bygger ved behov. Image build kjører et eksplisitt Docker-
bygg med vanlig cachebehandling. Velg en ny FROM-versjon når du vil endre base.
Byggingen bruker kontrollsidens nettverk. Registryendring i uendret FROM-tag
oppdages ikke som en lokal oppskriftsendring.

Kjørende brukere sperrer bygg. Stoppede brukere tillater bygg; du trenger ikke
fjerne miljøene først. Ved neste oppstart tas nytt image i bruk ved å erstatte
stoppet container. Umonterte profiler og annet containerinnhold kan da forsvinne;
bevar data i katalog-/volummounts. Et kjørende miljø beholdes med beskjed om at
endringer venter til neste oppstart. Start/exec åpner ikke en proxy som er stoppet
på et allerede kjørende miljø.

Remove fjerner bygget image/tag og beholder oppskriften. Både kjørende og
stoppede brukere sperrer remove. Inspect viser hvem som bruker oppskriftens
images, også når taggen er flyttet. Avledede images med egne referanser regnes
ikke som brukere bare fordi de arver image-labels.

Images må være amd64 eller arm64, støtte UID 0, `/bin/sh`, `sleep infinity`
og [CA-oppsettet](#api-tokens-i-proxyen). Dockerfile-deklarert VOLUME avvises;
velg registrerte mounts i miljøfilen. Alle agentimages bruker samme isolering.

Proxyimaget er en intern komponent som installeren bygger når det mangler.
`abx proxy build` bygger det på nytt fra installert kilde. Det vises ikke i
`image list` og har ingen brukeroppskrift. Alle containere med samme proxyimage-ID
må fjernes før bygging; stopp alene frigjør ikke imaget. For hvert berørt miljø:

```sh
abx stop example-codex
abx proxy stop example-codex
# Når alle berørte proxycontainere er fjernet:
abx proxy build
abx start example-codex
```

`proxy stop` fjerner proxycontaineren og dens tokenmetadata, mens agentens
containerlag beholdes. Uendret eksplisitt start eller proxy apply kan opprette
proxyen på nytt. Ved pending beholder start den eksisterende proxytilstanden.
Start/exec på kjørende agent beholder trafikken blokkert. Eksporter nødvendige
tokenvariabler før gjenopptak. Oppdatering av
kontrollkoden gjøres med installeren etter at miljøene er stoppet.

## Tab-completion i Bash

```sh
source <(abx completion bash)
```

Installeren legger inn completion for nye skall med `bash-completion` aktivert.
Tab foreslår kommandoer, flagg, eksisterende miljønavn, registrerte mounts
og lokale imageoppskrifter etter `image edit`, `build`, `inspect` og `remove`.
Etter `--template` foreslås lokale og medfølgende maler.
Etter `start`, `run`, `exec`, `validate` og `proxy apply` foreslås lagrede kortnavn og
lokale filstier.
Filstier fullføres også etter `--key-file`, og kataloger etter navnet i `mount add NAVN MAPPE`.
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
fjerning av miljøet; `remove` sletter containerlaget og umonterte profiler.

### Andre feil

| Feil | Årsak og neste steg |
| --- | --- |
| `launch_unknown` | Abx kan ikke bekrefte en tidligere exec; samme container-ID startes ikke før utfallet er kjent. Se [avbrutte kjøringer](#avbrutte-kjøringer) |
| `Working directory must be inside a registered mount` | Sett `workdir` lik `mounts[].target` eller en eksisterende undermappe |
| `No two collision-free /28 subnets` | Velg et ledig adresseområde etter [installasjonsveiledningen](installation.md#velg-adresseområde) |
| `Host addresses changed` | Vakten har stoppet miljøet. Neste start validerer oppsettet og kan erstatte laget; mountdata beholdes |
| Verktøy trenger Unix-sockets | Profilen blokkerer nye Unix-sockets. Velg kompatible verktøy; ikke svekk isoleringen automatisk |
