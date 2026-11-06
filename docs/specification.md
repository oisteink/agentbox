# Spesifikasjon for Agentbox

Agentbox kjører kodeagenter mot eksplisitt valgte prosjektmapper på én
Linux-vert. Én utvikler administrerer oppsettet og kan bruke flere miljøer
samtidig, med ulike images, mounts og nettverkspolicyer.

Dette er produktkontrakten for Agentbox. [Bruksveiledningen](usage.md)
beskriver kommandoene, [arkitekturen](architecture.md) forklarer oppbygningen,
og [teststatus](test-results.md) avgrenser hva som er verifisert.

Planlagte endringer i CLI og livssyklus står i [egen kravspesifikasjon](features/session-lifecycle/spec.md)
og er ikke del av kontrakten nedenfor.

Kommandonavnet er `abx`, både ved pakkeinstallasjon og vertsinstallasjon.
Hjelp, feilmeldinger og Bash-completion bruker dette navnet.

## Begreper og tillit

| Begrep | Betydning |
| --- | --- |
| Utvikler | Personlig Linux-bruker som registrerer prosjekter og styrer miljøer |
| Tjenestebruker | `agentbox`, som kjører rootless Docker uten vertens root-rettigheter |
| Prosjekt | Kanonisk vertsmappe med registrert identitet og eksplisitt tildelt tilgang |
| Miljø | Navngitt agentcontainer, proxy og egne nettverk med felles livssyklus |
| Miljøfil | YAML som velger image, kommando, arbeidskatalog, mounts og destinasjoner |
| Kontrollside | Installerte vertsprogrammer, privat tilstand og administrasjon av Docker |

Agenten og kode den kjører behandles som upålitelige. Utvikleren,
kontrollkoden, Docker, proxyen, valgte images og vertsadministrasjon er betrodd.
Miljøfiler oppbevares utenfor mapper agenten kan redigere. Kontrollkode og privat
kontrolltilstand monteres ikke inn i agentcontaineren. Bare miljøets offentlige
CA-katalog deles skrivebeskyttet inn fra kontrollsiden.

Rootless-containere deler vertens kjerne. Utbrudd med tjenestebrukerens
rettigheter kan gi tilgang til alle registrerte prosjekter og andre filer som
er tilgjengelige for lokale brukere. Tillatte destinasjoner kan brukes til å
sende data ut; domenepolicyen gir ingen innholdsfiltrering.

## Vertsplattform og kontroll

- Linux med systemd, cgroup v2, user namespaces, POSIX ACL og Python 3.12 eller nyere.
- Debian er målplattformen; Ubuntu brukes også til labprøver. Konkret minste
  Debian-versjon er ikke fastsatt utover forutsetningene over.
- Docker Engine og CLI 28 eller nyere. Den testede versjonen er 29.9.3;
  øvrige versjoner har ikke samme prøvegrunnlag.
- Egen Linux-bruker `agentbox`, privat hjem `/var/lib/agentbox` med modus 0700
  og egen Docker-konfigurasjon. Runtime-socket ligger under `/run/user/<uid>`.
- Administrator installerer kontrollkode under `/opt/agentbox` og innstillinger
  i `/etc/agentbox/settings.json`. Den private ACL-journalen ligger separat i
  `/var/lib/agentbox-operator` og eies av utvikleren.
- Installeren bruker `SUDO_USER` som standard utvikler. `--operator BRUKER`
  velger en annen bruker og kreves ved direkte root-kjøring. Root og
  tjenestebrukeren kan ikke være utvikler.
- Daglige Docker-operasjoner går via en fast sudo-hjelper som `agentbox`, med
  strukturert JSON på stdin og renset prosessmiljø. Fast socket, rootless-modus,
  daemon-ID, datasti, Docker-versjon og rapportert cgroup-støtte kontrolleres.
- Andre Docker-instansers konfigurasjon og context endres ikke. Docker-socketen
  eksponeres ikke over ubeskyttet TCP eller i agentcontainerne.

`doctor` kontrollerer daemonforutsetningene. Installeren kontrollerer
UID/GID-forutsetninger, `project check` kontrollerer prosjekttilgang, og labprøver
verifiserer faktisk håndheving av ressursgrenser.

## Prosjektregistrering og ACL

Prosjektet registreres uten flytting eller kopiering. Roten må eies av
utvikleren. Kanonisk sti og filsystemidentitet lagres; en erstattet rot
avvises ved miljøstart. Registrering med samme rot og fungerende tilgang er
idempotent.

ACL-er gir utvikleren og `agentbox` lese- og skrivetilgang. Kataloger og
allerede kjørbare filer får kjørbarhet; vanlige filer gjøres ikke kjørbare.
Nødvendige foreldrekataloger får traversering uten krav om listetilgang.
Standard-ACL-er støtter nye filer og kataloger. Restriktive filmoduser kan
kreve eksplisitt reparasjon.

Overlappende registreringer, hardlenkede ordinære filer, spesialfiler og eiere
utenfor utvikleren og tjenestebrukeren avvises. Symbolske lenker i innholdet
følges ikke ved ACL-endring, og skanningen krysser ikke nestede mountpunkter.
Kjente nestede mountpunkter hoppes over før åpning; privat målkatalog krever
ikke ekstra lesetilgang ved registrering, start eller avinstallasjon.
Ingen rekursiv `chown` brukes. Andre brukeres effektive rettigheter bevares ved
utvidet ACL-maske; tidligere maskerte rå biter kan trimmes.

Stopp endrer ikke prosjektregistrering eller ACL-er. Reparasjon og
tilbakekalling krever at alle berørte miljøer er stoppet, inkludert read-only-
brukere som ellers kan ha åpne filhåndtak. Tilbakekalling legger en navngitt
sperre for `agentbox` på prosjektroten. Filer, eierskap og innholdets ACL-er
beholdes. Sperren gjelder tilgangen gjennom roten og følger ikke filer som
flyttes eller deles gjennom andre vertsstier.

Foreldrenes administrerte ACL-er gjenopprettes når andre registreringer ikke
trenger dem. Oppdagede manuelle konflikter rapporteres fremfor å overskrives.
Delvis mislykket tildeling rapporteres som feil og krever retting eller
tilbakekalling.

## Miljøkonfigurasjon

`abx start FIL.yaml` leser miljønavnet fra `name` i miljøfilen.
Kommandoer mot eksisterende miljøer, som `shell` og `stop`, bruker miljønavnet.
`start`, `run`, `validate` og `proxy apply` støtter også kortnavn uten filending fra
`~/.config/agentbox/environments/` (eller `$XDG_CONFIG_HOME/agentbox/environments/`).
`.yaml` og `.yml` støttes. Hvis begge matcher, kreves eksplisitt filvalg.
Lokale filer uten filending overstyrer ikke kortnavn; bruk eksplisitt sti for slike filer.

YAML-filen avviser ukjente felter og dupliserte nøkler. Verdier for hemmeligheter,
vilkårlige Docker-flagg og automatisk hjemmedeling inngår ikke i skjemaet.
Prosjekt-, miljø- og imagenavn starter med en liten bokstav og bruker deretter
små bokstaver, tall og bindestrek, maksimalt 48 tegn.

| Felt | Kontrakt og standardverdi |
| --- | --- |
| `name` | Påkrevd unikt miljønavn; leses fra YAML-filen ved start |
| `image` | Påkrevd lokalt oppskriftsnavn, for eksempel `codex` eller `js` |
| `mounts` | 1 til 32 registrerte prosjekter, hvert med `project`, absolutt `target` og `mode` (`rw` som standard eller `ro`) |
| `workdir` | Sti inne i et prosjektmount; standard er første mountmål. Må finnes ved start |
| `persistent` | Boolsk, standard `true`. Med `false` fjerner `shell` miljøet etter kommandoen; `stop` fjerner det også |
| `command` | 1 til 128 ikke-tomme argumenter; standard `["bash"]`. Kjøres av `shell` og `run`, uten shelltolking |
| `network.allow` | Liste over eksakte `host`/`port`-par, maksimalt 128. Tom som standard |
| `credentials` | Maksimalt 32 regler med `host`, `port: 443`, `header` og `env`; tom som standard. Se [tokenreglene](#api-tokens-på-proxysiden) |
| `resources.cpus` | 0,1 til 128; standard 2 CPU |
| `resources.memory` | Positiv størrelse med `m` eller `g`; standard `4g` |
| `resources.pids` | 16 til 65536; standard 512 |

Mountmål som overlapper eller treffer reserverte systemstier avvises.
Kildemapper må være registrerte og eksistere; manglende mapper opprettes ikke.
Mountene har privat propagasjon og inkluderer ikke underliggende mounts.
Prosjektinnhold som `.env` blir tilgjengelig hvis det ligger i valgt mount.

Images må støtte amd64 eller arm64, UID 0, `/bin/sh` og `sleep infinity`.
Deklarerte `VOLUME`-mounts avvises. Det valgte imagets entrypoint erstattes
av miljøets oppholdsprosess; valgt arbeidskommando kjøres separat.
Imagevalg endrer ikke ACL-, nettverks- eller isoleringsmekanismene.

### Lokale imageoppskrifter

Alle agentimages har en lokal Dockerfile under `~/.config/agentbox/images/`
(eller `$XDG_CONFIG_HOME/agentbox/images/`). `image new NAVN` lager en ny
katalog med Dockerfile og .dockerignore uten overskriving. Standardmalen er
et generelt Linux-miljø. Eksempelmaler finnes for Codex 0.166.0
(`codex`), OpenCode 1.19.5 (`opencode`) og Claude Code 2.1.316 (`claude-code`).
Malene følger programmet; det finnes ingen separat standardkatalog i /usr/share.

`image ls` lister lokale oppskrifter, også ubygde, med status og image-ID.
`image edit NAVN` åpner Dockerfilen som utvikleren i VISUAL, deretter EDITOR,
ellers Debian sin editor-kommando. Whitespace-only variabler er tomme.
Siterte editorargumenter støttes uten shelltolking; terminal og miljø arves,
oppskriftskatalogen er arbeidskatalog, og editorens exitkode returneres.
Edit krever eksisterende oppskrift, men gjør ingen RPC eller bygging og
kan brukes mens imaget er i bruk.
`image inspect NAVN` viser sti, tag, ID og containere. `image build NAVN`
bygger katalogen i Agentbox sin rootless-instans, med vanlig COPY og
.dockerignore behandlet av Docker. Konteksten sendes uten generell ACL-tilgang
til utviklerens hjem; lenker derefereres ikke. Kontrollsiden pakker ut i en
privat midlertidig katalog med datafilter; lenker ut av konteksten og
spesialfiler avvises. Katalog og overført arkiv slettes etter byggingen.
Hele konteksten overføres til kontrollsiden, også filer builderen ignorerer.

Start krever både lokal oppskrift og et image bygget av Agentbox for samme
installasjon og navn. Dette gjelder også gjenopptak. Ingen automatisk bygg
eller pull ved start. Registryimages kan brukes i Dockerfilens FROM.

Bygg og `image rm NAVN` avvises når en eksisterende container bruker eksakt
samme image-ID, inkludert stoppede containere. Avledede images sperrer ikke.
Operasjonene deler kontrollsidens lås med start og remove. `image rm`
fjerner bygget tag, men beholder lokal oppskrift. Fjerning av miljøet
sletter containerlaget, inkludert hjem og innlogging.

Installeren bygger den interne proxykomponenten hvis imaget mangler, med
samme daemonverifikasjon og operasjonslås som kontrollverktøyet. Byggingen
kjører som agentbox med rent miljø; feil gir mislykket installasjon.
Eksisterende image beholdes, også når containere bruker det. `proxy build`
bygger komponenten eksplisitt fra installert kilde og beholder brukssperren.
Proxyen inngår ikke i image ls.

Agentens UID 0 mappes til tjenestebrukeren på verten. Den kjører med droppede
capabilities, `no-new-privileges`, ressursgrenser og en revisjonslåst Moby-
seccomp-profil med strengere sperrer mot Unix-sockets og alternative socket-
syscalls. Privilegert modus, vertsnettverk, vertens PID-namespace og ekstra
enheter tilbys ikke. Verktøy som trenger filsystem- eller abstrakte Unix-
sockets støttes ikke.

## Nettverk og proxy

Hvert miljø har et lukket `isolated` bridge-nettverk, et eksternt nettverk og
en egen Go-proxycontainer. Agenten kobles bare til det lukkede nettverket.
Proxyen har ett grensesnitt på hvert nett, lytter bare internt og videresender
ikke IP-trafikk. Ingen porter publiseres til vert eller LAN.

- Utgående agenttrafikk avvises som standard. Bare eksakte domene/port-par
  tillates, uten implisitte underdomener.
- HTTP på 80 og HTTPS via CONNECT på 443 støttes. Vanlig tillatt HTTPS er
  en tunnel. Eksplisitte credentials-regler aktiverer TLS-avlytting og
  headerinnsetting for valgt destinasjon, uten generelle sti-/body-regler.
- IP-litteraler og navn med ikke-offentlige adresser eller vertens egne adresser
  avvises. Kontrollsiden validerer alle DNS-svar og fastlåser én offentlig
  IPv4-adresse per navn. Proxyen har ingen ekstern DNS-fallback.
- Agentens IPv6 er deaktivert. Direkte ekstern TCP, UDP og QUIC samt tilgang
  til vert, LAN og andre miljøer blokkeres uavhengig av proxyvariabler.
  Agenten har ingen ubegrenset ekstern DNS-kanal.
- En adressevakt stopper miljøer ved endrede vertsadresser. Vakten er asynkron,
  deler lås med kontrolloperasjoner og gir ingen atomisk sperring i selve
  endringsøyeblikket. Nettverksadministrasjon på verten er betrodd.
- Proxyen får bare konfigurasjon og fastlåste adresser montert skrivebeskyttet.
  Ingen prosjektmapper eller Docker-socket deles inn i proxyen. API-tokens
  tilføres bare proxyens miljø ved start/apply; konfigurasjon har referanser.
- Bortfall av proxyen åpner ingen alternativ utgående vei.

Adresseområdet velges i administratorinnstillingen `network_pool`.
Det må ha minst to ledige `/28`-subnett; vertsruter og eksisterende nettverk
på Agentbox-daemonen utelukkes. Standardområdet er `172.28.0.0/16`.
Proxyens faste ressursgrenser er 0,5 CPU, 256 MiB og 128 prosesser.

Imagebygging og henting av baseimages skjer på den betrodde kontrollsiden utenfor
agentens nettverkspolicy. Agenten har ingen kontrollkanal for å bestille slike
operasjoner. Innloggingsdomener, API-er, MCP-tjenester og pakkeregistre må
velges eksplisitt for trafikk fra miljøet.

## Livssyklus, lagring og diagnostikk

| Operasjon | Oppførsel |
| --- | --- |
| `start FIL.yaml` | Leser miljønavnet fra filen, validerer miljø og mounts, oppretter nettverk og proxy før agent; uendret kjørende miljø gjenbrukes |
| `run FIL.yaml` | Kjører command én gang i terminalen i et nytt miljø; fjerner containere, nettverk og containerlag ved avslutning eller Ctrl-C; prosjektfiler beholdes |
| `shell` | Kjører miljøets konfigurerte kommando; med `persistent: false` fjernes miljøet etterpå, også ved feil eller Ctrl-C |
| `exec` | Kjører eksplisitt argumentliste i eksisterende miljø |
| `stop` | Med `persistent: true` stoppes agent og proxy og containerlaget beholdes; med `false` fjernes miljøet. Prosjektregistreringer beholdes |
| `remove` | Fjerner miljøets containere, nettverk og logger; prosjektfiler og ACL-er beholdes |
| `status` | Viser registrert miljøoppsett og observert containertilstand |
| `logs` | Viser et begrenset utsnitt av agentutdata eller proxylogg med `--proxy` |

Et stoppet miljø gjenopptas med uendret konfigurasjon og vertsadresser.

Med `persistent: true` beholdes containerens `/home/agent`, innlogging og
installerte filer, også ved manuell gjenopptak etter daemonrestart. Automatisk oppstart av miljøer
etter vertsreboot finnes ikke.

Endret agentprofil eller vertsadresse krever eksplisitt `remove` og ny
`start`. Da slettes containerlaget, inkludert innlogging og verktøyoppsett.
Montert kode består. Nettverk/tokenregler endres med proxy apply uten å slette
agentlaget. Gjenopptak av stoppet miljø og apply validerer DNS på nytt.

`persistent: false` gir ingen bevart container mellom shell-økter. Start
klargjør i bakgrunnen og varsler om miljøets levetid. Shell varsler før
kommandoen kjøres og reserverer én økt under lås. Flere shell-forsøk avvises uten opprydding av
den aktive økten. Reservasjonen beholdes ved start/proxy apply; etter et
hardt prosessavbrudd kreves eksplisitt remove. Exec er en ekstra kommando
og utløser ikke opprydding, men prosessen fjernes sammen med miljøet.

`run` er alltid midlertidig og avviser eksisterende miljønavn. Kommandoens
exitkode returneres etter vellykket opprydding; oppryddingsfeil gir feilstatus. Opprettelse og fjerning
bruker vanlig daemonverifikasjon og lås, mens kommandoen kjøres uten global
lås. Opprydding etter run og ikke-persistent shell sjekker valgt agent-ID
mot ny tilstand, slik at et gjenskapt miljø med samme navn ikke fjernes. SIGINT utsettes under kritiske mutasjoner.
SIGKILL og vertskrasj kan etterlate ressurser som må fjernes eksplisitt.

Terminalsesjoner i vedvarende miljøer har separat levetid fra miljøet.
`start` starter oppholdsprosessen, ikke `command`. `run`, `shell` og `exec`
bruker terminal bare når både CLI-ens stdin og stdout er terminaler og JSON
ikke er valgt. Uten terminal videresendes stdin, og stdout/stderr holdes atskilt.
Standardutskrift er for mennesker. `--json` gir JSON Lines med output-hendelser
og ett terminalt resultat med `ok`, `data` eller `error.code/message`, samt
`exit_code` for prosesser. Håndterte feil, kommandofeil og håndtert Ctrl-C gir
CLI-exitkode 0 i JSON-modus. Manglende terminalresultat er ikke suksess.
`--yes` gir samtykke; maskinmodus spør aldri interaktivt. Detaljert kontrakt
står i [bruksveiledningen](usage.md#utskrift-og-automatisering).
Terminalstørrelse og størrelsesendringer videresendes. Kontrolloperasjoner låses,
tilstand skrives atomisk, og opprydding avgrenses med ressurs-ID-er og
installasjons-/miljøetiketter. Global Docker-prune brukes ikke. Testavgrensninger
for krasj og samtidighet står i teststatus.

Agentnøkler gis eksplisitt per miljø. `login-api-key` krever en privat fil eid
av utvikleren og sender nøkkelen via stdin. Kontrollverktøyet logger ikke
nøkkelverdier eller forespørsler. Agentens egne utdata kan inneholde hemmeligheter;
disse loggene er private og roterte uten generell filtrering. Proxyloggen
inneholder destinasjon og resultat uten URL-sti eller query.

CLI-en tilbyr Bash-completion for kommandoer, flagg, registrerte prosjekter,
eksisterende miljøer og relevante filstier. Dynamiske navneoppslag ber ikke om
sudo-passord og har en tidsgrense på to sekunder.

## Verifikasjonskriterier

Integrasjonsprøver bruker midlertidige mapper og kontrollerte
nettverksdestinasjoner. Forventet
blokkering bekreftes mot en fungerende kontrolltjeneste. Observerte resultater,
manuell utprøving og utestede kombinasjoner står i [teststatus](test-results.md).
Testenes ansvar, kravdekning og regler ved endringer står i
[teststrategien](testing.md). Bevaring skal undersøkes utenfor prosjektmountene;
negative prøver skal bekrefte riktig avvisning og relevante konsekvenser.

| ID | Verifikasjon |
| --- | --- |
| A1 | Miljøet bruker riktig daemon; feil eller rootful daemon avvises |
| A2 | To miljøer kjører samtidig; stopp og opprydding av ett lar det andre fortsette |
| A3 | Bare valgte vertsmapper er synlige; en kontrollmappe ved siden av prosjektet er utilgjengelig |
| A4 | Begge brukerne kan opprette, redigere, erstatte og slette testfiler; kjørbare filer beholder kjørbarhet |
| A5 | Skrivebeskyttede mounts avviser skriving; kodeendringer overlever fjerning av miljøet |
| A6 | Tillatte HTTP- og HTTPS-destinasjoner fungerer gjennom proxy; andre domener og porter avvises |
| A7 | Direkte IPv4/IPv6 og UDP blokkeres uten proxyvariabler; vert, LAN og andre miljøer er utilgjengelige |
| A8 | DNS gir ingen ubegrenset ekstern kanal; tillatt navn som peker til intern adresse avvises |
| A9 | Stoppet proxy og ugyldig policy gir ingen alternativ utgående tilgang |
| A10 | Agenten kan ikke endre policy, nå Docker-socketen eller opprette egne mounts/nettverk |
| A11 | To images fungerer med samme kontroll-, mount- og nettverksmekanisme |
| A12 | CPU-, minne- og prosessgrenser verifiseres; manglende støtte gir feil |
| A13 | Tilbakekalling av prosjekttilgang bevarer uvedkommende ACL-er og tilgang til andre registrerte prosjekter |

## Avinstallasjon

`sudo scripts/uninstall.sh` er en administratoroperasjon som stopper alle Agentbox-
miljøer, overfører tjenestebrukerens prosjektfiler til utviklerens UID/GID og
fjerner installasjon, tjenester, hjem, images, privat tilstand og tjenestebruker.
`--dry-run` viser omfanget uten å endre filer eller tjenester. Løpende miljøer
gir en advarsel og stoppes; brukeren trenger ikke avvikle dem manuelt først.

Tilbakekalte prosjekter i registeret inngår i filryddingen. Røttene valideres mot
lagret identitet. Symlinker følges ikke, men selve linkens eierskap overføres.
Nestede mounts hoppes over, og berørte hardlenker avvises for å unngå endring
av filer utenfor prosjektet. Prosjektinnhold og brukerens miljøfiler beholdes.

Kun tjenestebrukerens ACL-oppføringer fjernes fra innholdet; øvrige oppføringer
og masker beholdes. Journalførte foreldre gjenopprettes når uendret, ellers
fjernes bare tjenestebrukerens oppføring. Prosjektrydding må lykkes før
konto og installasjonsdata slettes. Operasjonen tar journal- og kontrollås i
samme rekkefølge som prosjektoperasjonene og stenger den vanlige sudo-hjelperen
før prosesser stoppes. Den gir ikke nye root-rettigheter gjennom den vanlige
kontrollhjelperen.

## Utenfor denne leveransen

- Linked worktrees og deres delte Git-metadata.
- Egen vertsbruker eller VM per prosjekt og sterkere runtime som gVisor.
- Separat profillagring som overlever fjerning av miljøet.
- Generelle URL-/body-regler, vilkårlig TCP-proxy og utgående SSH.
- GUI, fjernkjøring, flerbrukerplattform og automatisk håndtering av agentkontoer.

Videre vurdering omfatter sammenligning med OpenShell og Docker Sandboxes.
Arbeidet skal undersøke faktiske isoleringsgrenser, nettverkspolicy, mounts,
filrettigheter, samtidige miljøer, imagevalg, plattformkrav og vedlikehold.

## API-tokens på proxysiden

`credentials` kobler en tillatt host/443 og auth-header til en navngitt
vertsvariabel. `env: klient=kilde` leser høyresiden fra operatørens prosessmiljø;
`env: klient` bruker samme navn på begge sider. Verdien er en rå nøkkel,
uten Bearer-prefiks.

Ved opprettelse får agentens klientvariabel en unik plassholder når kilden
har verdi, ellers en tom streng. Den ekte nøkkelen gis bare til proxyens
miljø og inngår ikke i config, policy, tilstand eller argumenter. Agenten får
offentlig CA/bundle; privat CA forblir på den betrodde siden. Docker lagrer
proxyens miljø som metadata, som kan leses ved fullt utbrudd til tjenestebrukeren.
Se [praktisk oppsett](usage.md#api-tokens-i-proxyen).

### Krav til headerutskifting

En nøkkelregel må også finnes i `network.allow`. Samme klientnavn må vise
til samme kilde i alle miljøets regler. Flere klientnavn kan dele kilde og
får egne plassholdere. Bare klientnavnet valideres mot reserverte runtime-navn;
konfigurasjonen er betrodd og skal ligge utenfor agentens skrivbare mapper.

Tillatte auth-headere er Authorization, X-API-Key og CONTEXT7_API_KEY.
Match bare hele plassholderen eller den etter Bearer-prefiks. Prefikset
beholdes; dupliserte relevante headere og tvetydige aliaser avvises. Navn
normaliseres til små bokstaver med `_` lik `-`. Bare GET, HEAD, POST, PUT,
PATCH, DELETE og OPTIONS tillates på avlyttet trafikk; deklarerte trailere
og Upgrade avvises. URL/body omfattes ikke av utskifting.

CONNECT-destinasjon, SNI og Host/authority må være konsistente for hver
request, også på gjenbrukte forbindelser. Upstream bruker godkjent pin og
validert sertifikatnavn; ingen DNS-/proxy-fallback eller automatisk redirect.
En eksplisitt tom regel beholder TLS-inspeksjon, men kan ikke ha ekte token.
Vanlige requests uten plassholder kan videresendes uten nøkkelinnsetting.

### Levetid og tilbakekalling

Miljøets plassholderkart lagres uten ekte nøkler. Det er fast gjennom
agentcontainerens levetid. Tom/ikke-tom overgang krever gjenskaping;
`remove` sletter hjem/innlogging, men ikke monterte prosjektfiler.

Apply sjekker først profil, klientnavn, mounts og nettverk. Avslag her endrer
ikke eksisterende proxy; feilen viser `proxy stop` for tilbakekalling.
Etter denne kontrollen fjernes gammel proxy før tokenvalidering og kontroll
av tilgjengelighet. Senere feil gjenoppretter ikke gamle nøkler. Gjentatt
start av et uendret kjørende miljø leser ikke kildene på nytt.

`proxy stop` er eksplisitt lokal tilbakekalling. Unset alene endrer ikke
kjørende proxyer. Tilbakekalling hos API-leverandøren er en separat operasjon.
Fjernes nøkkelregelen eksplisitt, kan nettverkspolicyen igjen tillate vanlig
tunnel. Den ekte nøkkelen settes aldri inn i en slik tunnel.
