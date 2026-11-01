# Spesifikasjon for Agentbox

Agentbox kjører kodeagenter mot eksplisitt valgte prosjektmapper på én
Linux-vert. Én utvikler administrerer oppsettet og kan bruke flere miljøer
samtidig, med ulike images, mounts og nettverkspolicyer.

Dette er produktkontrakten for utviklingsgrenen med Go-proxy. [Bruksveiledningen](usage.md)
beskriver kommandoene, [arkitekturen](architecture.md) forklarer oppbygningen,
og [teststatus](test-results.md) avgrenser hva som er verifisert.

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
Miljøfiler oppbevares utenfor mapper agenten kan redigere. Kontrollkode og
kontrolltilstand monteres ikke inn i agentcontaineren.

Rootless-containere deler vertens kjerne. Utbrudd med tjenestebrukerens
rettigheter kan gi tilgang til alle registrerte prosjekter og andre filer som
er tilgjengelige for lokale brukere. Tillatte destinasjoner kan brukes til å
sende data ut; domenepolicyen gir ingen innholdsfiltrering.

## Vertsplattform og kontroll

- Linux med systemd, cgroup v2, user namespaces, POSIX ACL og Python 3.12 eller nyere.
- Debian er målplattformen; Ubuntu brukes også til labprøver. Konkret minste
  Debian-versjon er ikke fastsatt utover forutsetningene over.
- Docker Engine og CLI 28 eller nyere. Den testede versjonen er 29.9.2;
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

Fra 1.0.1 brukes `agentbox start FIL.yaml`. Miljønavnet
leses fra `name`; et separat navneargument og `--config` er fjernet.
Kommandoer mot eksisterende miljøer, som `shell` og `stop`, bruker miljønavnet.
`start` og `validate` støtter også kortnavn uten filending fra
`~/.config/agentbox/environments/` (eller `$XDG_CONFIG_HOME/agentbox/environments/`).
`.yaml` og `.yml` støttes. Hvis begge matcher, kreves eksplisitt filvalg.
Lokale filer uten filending overstyrer ikke kortnavn; bruk eksplisitt sti for slike filer.

YAML-filen avviser ukjente felter og dupliserte nøkler. Verdier for hemmeligheter,
vilkårlige Docker-flagg og automatisk hjemmedeling inngår ikke i skjemaet.
Prosjekt- og miljønavn bruker små bokstaver, tall og bindestrek, maksimalt 48 tegn.

| Felt | Kontrakt og standardverdi |
| --- | --- |
| `name` | Påkrevd unikt miljønavn; leses fra YAML-filen ved start |
| `image` | Påkrevd image; `agentbox-dev:local` inneholder Codex 0.166.0 |
| `mounts` | 1 til 32 registrerte prosjekter, hvert med `project`, absolutt `target` og `mode` (`rw` som standard eller `ro`) |
| `workdir` | Sti inne i et prosjektmount; standard er første mountmål. Må finnes ved start |
| `command` | Ikke-tom argumentliste; standard `["bash"]`. Kjøres av `shell` |
| `network.allow` | Liste over eksakte `host`/`port`-par, maksimalt 128. Tom som standard |
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

Agentens UID 0 mappes til tjenestebrukeren på verten. Den kjører med droppede
capabilities, `no-new-privileges`, ressursgrenser og en revisjonslåst Moby-
seccomp-profil med strengere sperrer mot Unix-sockets og alternative socket-
syscalls. Privilegert modus, vertsnettverk, vertens PID-namespace og ekstra
enheter tilbys ikke. Verktøy som trenger filsystem- eller abstrakte Unix-
sockets faller utenfor kompatibiliteten i 1.0.

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

Imagebygging og imagehenting skjer på den betrodde kontrollsiden utenfor
agentens nettverkspolicy. Agenten har ingen kontrollkanal for å bestille slike
operasjoner. Innloggingsdomener, API-er, MCP-tjenester og pakkeregistre må
velges eksplisitt for trafikk fra miljøet.

## Livssyklus, lagring og diagnostikk

| Operasjon | Oppførsel |
| --- | --- |
| `start FIL.yaml` | Leser miljønavnet fra filen, validerer miljø og mounts, oppretter nettverk og proxy før agent; uendret kjørende miljø gjenbrukes |
| `shell` | Kjører miljøets konfigurerte kommando i en terminalsesjon |
| `exec` | Kjører eksplisitt argumentliste i eksisterende miljø |
| `stop` | Stopper agent og proxy, bevarer containerlaget og registreringene |
| `remove` | Fjerner miljøets containere, nettverk og logger; prosjektfiler og ACL-er beholdes |
| `status` | Viser registrert miljøoppsett og observert containertilstand |
| `logs` | Viser et begrenset utsnitt av agentutdata eller proxylogg med `--proxy` |

Et stoppet miljø gjenopptas med uendret konfigurasjon og vertsadresser.
Containerens `/home/agent`, innlogging og installerte filer beholdes, også
ved manuell gjenopptak etter daemonrestart. Automatisk oppstart av miljøer
etter vertsreboot finnes ikke.

Endret agentprofil eller vertsadresse krever eksplisitt `remove` og ny
`start`. Da slettes containerlaget, inkludert innlogging og verktøyoppsett.
Montert kode består. Nettverk/tokenregler endres med proxy apply uten å slette
agentlaget. Gjenopptak av stoppet Go-miljø og apply validerer DNS på nytt.

Terminalsesjoner har separat levetid fra miljøet. Størrelse og størrelsesendringer
videresendes. Kontrolloperasjoner låses, tilstand skrives atomisk, og opprydding
avgrenses med ressurs-ID-er og installasjons-/miljøetiketter. Global Docker-
prune brukes ikke. Testavgrensninger for krasj og samtidighet står i teststatus.

Agentnøkler gis eksplisitt per miljø. `login-api-key` krever en privat fil eid
av utvikleren og sender nøkkelen via stdin. Kontrollverktøyet logger ikke
nøkkelverdier eller forespørsler. Agentens egne utdata kan inneholde hemmeligheter;
disse loggene er private og roterte uten generell filtrering. Proxyloggen
inneholder destinasjon og resultat uten URL-sti eller query.

CLI-en tilbyr Bash-completion for kommandoer, flagg, registrerte prosjekter,
eksisterende miljøer og relevante filstier. Dynamiske navneoppslag ber ikke om
sudo-passord og har en tidsgrense på to sekunder.

## Verifikasjonskriterier

Kriteriene A1 til A13 videreføres fra utviklingen av 1.0. Integrasjonsprøver
bruker midlertidige mapper og kontrollerte nettverksdestinasjoner. Forventet
blokkering bekreftes mot en fungerende kontrolltjeneste. Observerte resultater,
manuell utprøving og utestede kombinasjoner står i [teststatus](test-results.md).

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

## Avinstallasjon i 1.0.1

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
